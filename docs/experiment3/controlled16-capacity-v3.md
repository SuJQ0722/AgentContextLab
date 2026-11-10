# Controlled16 capacity transition

The user authorized the original controlled-baseline queue to run with 16 native workers. This operational change preserves the frozen scientific plan, original eligible 120 arms, and per-group controls.

The existing RQ3 .7 controller receives a dispatch-stop marker and drains existing native attempts naturally. No native process group is killed. Before transition, reserve one slot for the old controlled pilot. Once the proven stopped .7 upper bound is at most 10, the global bound is:

```
4 running RQ3 cells × 16 + draining .7 ≤ 10
+ BC Hermes16 + BC DSH16 + controlled16 + other model reserve6 ≤128
```

The controlled16 reservation **includes** the adopted old pilot. The capacity marker binds the original plan SHA, the new dispatcher SHA, and the two exact old coordinator identities. The dispatcher stops only those coordinators and takes over the queue lock; existing native work remains in the same 16-slot cap.

The new capacity authority is `scripts/bc_controlled_capacity_ops_v3.py --watch --live`. It shares the previous authority's `observer.lock`, so the old v2 watcher must exit before v3 can run. The exact old watcher identity at preparation was PID560362/start897984973, running `scripts/bc_priority_capacity_ops_v2.py --watch --live`. Main verifies identity and argv using a pidfd before signaling only that watcher. Neither the old scientific controller nor v2 source is edited.

The launch marker is `outputs/cloud-runtime/bc-controlled-capacity-ops-v3/markers/controlled16.json`. After it is published, 16 slots remain reserved until the dispatcher reports all120 eligible arms resolved, no native or unknown occupancy, and its identity has exited. Missing or contradictory evidence does not release capacity. Six additional model-task slots remain reserved for grading/other model work.

RQ3 .7 may be restored in a new CCI as soon as capacity and native-drain/old-CCI-stop evidence permit. RQ3 .8 and1 still wait until both BC cells finish. All three restorations are checked cumulatively; seven RQ3 cells plus controlled16 plus six reserved slots would be134 and are therefore prohibited. Some held cell can wait for another RQ3 cell to finish. New CCI names are `acl-rq3-controlled16-v3-s0700`, `...-s0800`, and `...-s1000`, each16 workers, with separate markers and generation receipts.

Preparation, marker and capacity tests make no paid model calls. The live capacity authority performs only the user-authorized scheduling/CCI operations; actual paid work belongs to the independent frozen experiment workers.
