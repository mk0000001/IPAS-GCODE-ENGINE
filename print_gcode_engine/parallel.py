"""Bounded-file multiprocessing with modal checkpoints and ordered merging."""
from concurrent.futures import ProcessPoolExecutor, wait
from contextlib import ExitStack
from decimal import localcontext
from pathlib import Path
from queue import Empty, Full
import multiprocessing
import re

from .checkpoint import segment_checkpoints
from .merge import merge_chunks
from .scanner import scan


def benefits_from_parallel(sample,*,size_bytes=0,native=False):
    """Large dense native workloads and arc-heavy files benefit in VM tests."""
    commands=re.finditer(rb'(?m)^\s*(?:N\d+\s*)?G([0123])(?=\s|[XYZIJKREF])',sample)
    total=arcs=0
    for command in commands:
        total+=1
        if command[1] in (b'2',b'3'):arcs+=1
    if total<100:return False
    if native and size_bytes>=128*1024**2 and total>=len(sample)/200:return True
    return arcs/total>=.08


class BoundedReader:
    def __init__(self,stream,start,end):
        self.stream=stream;self.start=start;self.end=end;self.position=start;stream.seek(start)
    def tell(self):return self.position-self.start
    def readline(self,limit=-1):
        remaining=self.end-self.position
        if remaining<=0:return b''
        data=self.stream.readline(min(remaining,limit) if limit>=0 else remaining)
        self.position+=len(data)
        return data


def _piece(path,start,end,state,index,event,updates):
    def progress(value):
        # Progress is advisory. A slow parent must not stall geometry parsing or
        # cancellation because its bounded notification queue is temporarily full.
        try:updates.put_nowait((index,value['bytes_processed'],value['lines']))
        except Full:pass
    with localcontext() as context:
        context.prec=50
        with Path(path).open('rb') as stream:
            return scan(BoundedReader(stream,start,end),end-start,progress,event.is_set,initial_state=state,include_internal=True)


def analyze_parallel_file(path,progress=None,cancelled=None,workers=4,*,parts=None):
    """Overlap checkpoint production and bounded, source-ordered chunk scans.

    Smaller chunks hide the serial prefix on large files. At most 32 summaries
    are retained; the progress queue is bounded and only ``workers`` processes
    run. Small inputs keep the former partition count to avoid extra task cost.
    """
    path=Path(path);size=path.stat().st_size
    if workers<2 or workers>8:raise ValueError('INVALID_WORKER_COUNT')
    parts=(workers*4 if size>=32*1024**2 else workers) if parts is None else parts
    if not isinstance(parts,int) or parts<2 or parts>32:raise ValueError('INVALID_SEGMENT_COUNT')
    checkpoint_total=max(1,int(size*(parts-1)/parts))
    checkpoint_bytes=checkpoint_lines=last_lines=0
    producing=True;pool=event=updates=None
    futures=[];ranges=[];counts={};completed=set()

    def collect():
        if updates is None:return
        while True:
            try:
                index,processed,lines=updates.get_nowait()
                if index not in completed:
                    old=counts.get(index,(0,0))
                    counts[index]=(max(old[0],processed),max(old[1],lines))
            except Empty:break
        for index,future in enumerate(futures):
            if index not in completed and future.done():
                value=future.result()  # Surface worker validation errors during the prepass.
                counts[index]=(ranges[index][1]-ranges[index][0],value['lines'])
                completed.add(index)

    def check_cancelled():
        collect()
        return bool(cancelled and cancelled())

    def emit():
        nonlocal last_lines
        collect()
        if not progress:return
        processed=sum(row[0] for row in counts.values())
        last_lines=max(last_lines,checkpoint_lines,sum(row[1] for row in counts.values()))
        fraction=min(1,checkpoint_bytes/checkpoint_total) if producing else 1
        progress({'bytes_processed':min(size,int(size*.25*fraction+processed*.75)),
                  'total_bytes':size,'lines':last_lines,
                  'phase':'CHECKPOINT' if producing else 'PARALLEL','workers':min(workers,len(futures)),
                  'phase_bytes_processed':checkpoint_bytes if producing else processed,
                  'phase_total_bytes':checkpoint_total if producing else size,'eta_final_phase':not producing,
                  'completed_chunks':len(completed),'submitted_chunks':len(futures)})

    def checkpoint_progress(value):
        nonlocal checkpoint_bytes,checkpoint_lines
        checkpoint_bytes=max(checkpoint_bytes,value['bytes_processed'])
        checkpoint_lines=max(checkpoint_lines,value['lines'])
        emit()

    with ExitStack() as stack:
        def submit(segment):
            nonlocal pool,event,updates,checkpoint_bytes
            if check_cancelled():raise RuntimeError('ANALYSIS_CANCELLED')
            if pool is None:
                context=multiprocessing.get_context('spawn')
                manager=stack.enter_context(context.Manager())
                event=manager.Event();updates=manager.Queue(maxsize=workers*8)
                pool=stack.enter_context(ProcessPoolExecutor(max_workers=workers,mp_context=context))
            start,end,state=segment
            index=len(futures);ranges.append((start,end))
            futures.append(pool.submit(_piece,str(path),start,end,state,index,event,updates))
            checkpoint_bytes=max(checkpoint_bytes,min(end,checkpoint_total))
            emit()

        try:
            segments=segment_checkpoints(path,workers,cancelled=check_cancelled,
                                         progress=checkpoint_progress,on_segment=submit,parts=parts)
            if not segments:
                with localcontext() as context:
                    context.prec=50
                    with path.open('rb') as stream:return scan(stream,size,progress,cancelled)
            producing=False
            while True:
                if check_cancelled():raise RuntimeError('ANALYSIS_CANCELLED')
                _,pending=wait(futures,timeout=.25)
                emit()
                if not pending:break
            result=merge_chunks([future.result() for future in futures])
        except BaseException:
            # This must execute before ExitStack waits for the process pool.
            if event is not None:event.set()
            for future in futures:future.cancel()
            raise
    result['analysis_execution']={'mode':'MULTIPROCESS','workers':min(workers,len(segments)),
                                  'chunks':len(segments),'pipelined':True}
    if progress:progress({'bytes_processed':size,'total_bytes':size,'lines':result['lines'],
                          'phase':'COMPLETE','workers':min(workers,len(segments))})
    return result
