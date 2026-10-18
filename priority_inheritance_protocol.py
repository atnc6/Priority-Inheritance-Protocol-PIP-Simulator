#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Real-Time Operating System (RTOS) Scheduler Simulator
Topic: Priority Inheritance Protocol (PIP) vs. Priority Inversion
File: priority_inheritance_protocol.py
Course: Embedded and Real-Time Systems
Dependencies: None (Pure Python 3 Standard Library)
"""

import sys
import os
import copy
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

# Ensure UTF-8 output on Windows CMD / PowerShell so box-drawing characters render cleanly
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ==============================================================================
# 1. DATA STRUCTURES & MODELS
# ==============================================================================

@dataclass
class Phase:
    """
    Represents an execution phase of a real-time task.
    If resource is None, it is a normal CPU burst.
    If resource is a string (e.g., 'R1'), the task locks that mutex during this phase.
    """
    resource: Optional[str]
    duration: int


@dataclass
class TaskSpec:
    """Input specification for a real-time task."""
    name: str
    arrival_time: int
    base_priority: int  # Higher number = Higher priority (e.g., 3=High, 2=Med, 1=Low)
    phases: List[Phase]

    @property
    def total_burst(self) -> int:
        return sum(p.duration for p in self.phases)


@dataclass
class TaskRuntime:
    """Tracks the dynamic state of a task during simulation."""
    spec: TaskSpec
    current_phase_idx: int = 0
    phase_remaining: int = 0
    effective_priority: int = 0
    state: str = "NOT_ARRIVED"  # NOT_ARRIVED, READY, RUNNING, BLOCKED, COMPLETED
    holding_resources: List[str] = field(default_factory=list)
    waiting_for_resource: Optional[str] = None
    first_start_time: Optional[int] = None
    completion_time: Optional[int] = None
    ready_wait_ticks: int = 0
    blocked_ticks: int = 0
    inherited_run_ticks: int = 0

    def __post_init__(self):
        self.effective_priority = self.spec.base_priority
        if self.spec.phases:
            self.phase_remaining = self.spec.phases[0].duration


@dataclass
class TickRecord:
    """Stores the exact system snapshot during time [t, t+1]."""
    tick: int
    running_task: Optional[str]
    running_resource: Optional[str]
    base_prio: Optional[int]
    effective_prio: Optional[int]
    is_inherited: bool
    task_states: Dict[str, str]
    resource_owners: Dict[str, Optional[str]]
    priority_inversion_active: bool


@dataclass
class SimulationResult:
    """Container for all outputs of a single simulation run."""
    protocol_name: str
    use_pip: bool
    timeline: List[TickRecord]
    events: List[Tuple[int, str]]
    tasks: Dict[str, TaskRuntime]
    inversion_ticks: int
    total_ticks: int


# ==============================================================================
# 2. RTOS SCHEDULER & PIP ENGINE
# ==============================================================================

class RTOSSimulator:
    """
    Discrete-time preemptive priority-based RTOS kernel simulator.
    Supports both Standard Priority Scheduling (prone to Priority Inversion)
    and Priority Inheritance Protocol (PIP).
    """

    def __init__(self, task_specs: List[TaskSpec], use_pip: bool = True):
        self.task_specs = copy.deepcopy(task_specs)
        self.use_pip = use_pip
        self.tasks: Dict[str, TaskRuntime] = {
            spec.name: TaskRuntime(spec=spec) for spec in self.task_specs
        }
        self.resources: Dict[str, Optional[str]] = {}
        for spec in self.task_specs:
            for phase in spec.phases:
                if phase.resource and phase.resource not in self.resources:
                    self.resources[phase.resource] = None

        self.events: List[Tuple[int, str]] = []
        self.timeline: List[TickRecord] = []
        self.current_tick: int = 0
        self.max_simulation_ticks: int = 200

    def log_event(self, message: str):
        self.events.append((self.current_tick, message))

    def _recalculate_priorities(self):
        """
        Implements the Priority Inheritance Protocol (PIP) rule:
        1. Reset all active tasks to their base_priority.
        2. Transitively propagate effective_priority: if Task A is BLOCKED waiting
           for Resource R, and Task B holds Resource R, then:
           Task B's effective_priority = max(Task B's effective_priority, Task A's effective_priority).
        """
        old_priorities = {name: t.effective_priority for name, t in self.tasks.items()}

        for t in self.tasks.values():
            t.effective_priority = t.spec.base_priority

        if not self.use_pip:
            return

        changed = True
        while changed:
            changed = False
            for waiter in self.tasks.values():
                if waiter.state == "BLOCKED" and waiter.waiting_for_resource:
                    res = waiter.waiting_for_resource
                    owner_name = self.resources.get(res)
                    if owner_name:
                        owner = self.tasks[owner_name]
                        if waiter.effective_priority > owner.effective_priority:
                            owner.effective_priority = waiter.effective_priority
                            changed = True

        for name, t in self.tasks.items():
            old_p = old_priorities[name]
            new_p = t.effective_priority
            if new_p > old_p:
                self.log_event(
                    f"[PIP BOOST] {name} inherits Priority {new_p} (Base: {t.spec.base_priority}) "
                    f"while holding {t.holding_resources}"
                )
            elif new_p < old_p:
                self.log_event(
                    f"[PIP RESTORE] {name} priority restored from {old_p} back to {new_p}"
                )

    def _release_completed_phase_resources(self, task: TaskRuntime):
        """Releases a resource if the task just finished a critical section phase."""
        completed_phase = task.spec.phases[task.current_phase_idx]
        res = completed_phase.resource
        if res and res in task.holding_resources:
            next_idx = task.current_phase_idx + 1
            if next_idx < len(task.spec.phases) and task.spec.phases[next_idx].resource == res:
                return

            self.resources[res] = None
            task.holding_resources.remove(res)
            self.log_event(f"[UNLOCK] {task.spec.name} released resource '{res}'")

            for other in self.tasks.values():
                if other.state == "BLOCKED" and other.waiting_for_resource == res:
                    other.state = "READY"
                    other.waiting_for_resource = None
                    self.log_event(f"[WAKEUP] {other.spec.name} unblocked (resource '{res}' is now free)")

            self._recalculate_priorities()

    def _all_completed(self) -> bool:
        return all(t.state == "COMPLETED" for t in self.tasks.values())

    def run(self) -> SimulationResult:
        """Executes the discrete-time RTOS simulation tick-by-tick."""
        inversion_ticks = 0

        while not self._all_completed() and self.current_tick < self.max_simulation_ticks:
            t = self.current_tick

            # 1. Check for newly arriving tasks at tick t
            for task in self.tasks.values():
                if task.state == "NOT_ARRIVED" and task.spec.arrival_time == t:
                    task.state = "READY"
                    self.log_event(
                        f"[ARRIVAL] {task.spec.name} arrived (Base Priority: {task.spec.base_priority})"
                    )

            # 2. Resource Resolution Loop
            selected_task: Optional[TaskRuntime] = None

            while True:
                ready_tasks = [
                    task for task in self.tasks.values()
                    if task.state in ("READY", "RUNNING")
                ]
                if not ready_tasks:
                    selected_task = None
                    break

                for rt in ready_tasks:
                    rt.state = "READY"

                ready_tasks.sort(
                    key=lambda x: (-x.effective_priority, x.spec.arrival_time, x.spec.name)
                )
                candidate = ready_tasks[0]
                current_phase = candidate.spec.phases[candidate.current_phase_idx]
                needed_res = current_phase.resource

                if needed_res is None:
                    selected_task = candidate
                    break

                owner = self.resources[needed_res]
                if owner is None:
                    self.resources[needed_res] = candidate.spec.name
                    candidate.holding_resources.append(needed_res)
                    self.log_event(f"[LOCK] {candidate.spec.name} acquired resource '{needed_res}'")
                    selected_task = candidate
                    break
                elif owner == candidate.spec.name:
                    selected_task = candidate
                    break
                else:
                    candidate.state = "BLOCKED"
                    candidate.waiting_for_resource = needed_res
                    self.log_event(
                        f"[BLOCKED] {candidate.spec.name} (Prio {candidate.effective_priority}) "
                        f"blocked on '{needed_res}' (held by {owner})"
                    )
                    self._recalculate_priorities()

            # 3. Execute the selected task for 1 tick [t, t+1]
            running_name = None
            running_res = None
            base_p = None
            eff_p = None
            is_inh = False

            if selected_task is not None:
                selected_task.state = "RUNNING"
                if selected_task.first_start_time is None:
                    selected_task.first_start_time = t

                running_name = selected_task.spec.name
                running_res = selected_task.spec.phases[selected_task.current_phase_idx].resource
                base_p = selected_task.spec.base_priority
                eff_p = selected_task.effective_priority
                is_inh = eff_p > base_p
                if is_inh:
                    selected_task.inherited_run_ticks += 1

            # 4. Detect Priority Inversion during this tick
            pi_active = False
            if selected_task is not None:
                blocked_tasks = [tk for tk in self.tasks.values() if tk.state == "BLOCKED"]
                for bt in blocked_tasks:
                    if bt.spec.base_priority > selected_task.spec.base_priority:
                        lock_owner_name = self.resources.get(bt.waiting_for_resource)
                        if selected_task.spec.name != lock_owner_name:
                            pi_active = True
                            break

            if pi_active:
                inversion_ticks += 1

            # 5. Record states and update counters for all tasks during [t, t+1]
            state_snapshot: Dict[str, str] = {}
            for name, tk in self.tasks.items():
                if tk.state == "RUNNING":
                    if is_inh:
                        state_snapshot[name] = "RUN_INH"
                    elif running_res:
                        state_snapshot[name] = "RUN_CS"
                    else:
                        state_snapshot[name] = "RUN_CPU"
                elif tk.state == "READY":
                    tk.ready_wait_ticks += 1
                    state_snapshot[name] = "READY"
                elif tk.state == "BLOCKED":
                    tk.blocked_ticks += 1
                    state_snapshot[name] = "BLOCKED"
                elif tk.state == "COMPLETED":
                    state_snapshot[name] = "DONE"
                else:
                    state_snapshot[name] = "NONE"

            self.timeline.append(
                TickRecord(
                    tick=t,
                    running_task=running_name,
                    running_resource=running_res,
                    base_prio=base_p,
                    effective_prio=eff_p,
                    is_inherited=is_inh,
                    task_states=state_snapshot,
                    resource_owners=copy.deepcopy(self.resources),
                    priority_inversion_active=pi_active,
                )
            )

            # 6. Advance time to t + 1 and update phase progress
            self.current_tick += 1

            if selected_task is not None:
                selected_task.phase_remaining -= 1
                if selected_task.phase_remaining == 0:
                    self._release_completed_phase_resources(selected_task)
                    selected_task.current_phase_idx += 1

                    if selected_task.current_phase_idx >= len(selected_task.spec.phases):
                        selected_task.state = "COMPLETED"
                        selected_task.completion_time = self.current_tick
                        self.log_event(f"[COMPLETE] {selected_task.spec.name} finished execution")
                    else:
                        selected_task.phase_remaining = (
                            selected_task.spec.phases[selected_task.current_phase_idx].duration
                        )
                        selected_task.state = "READY"

        protocol_title = (
            "Priority Inheritance Protocol (WITH PIP)"
            if self.use_pip
            else "Standard Priority Scheduling (WITHOUT PIP)"
        )
        return SimulationResult(
            protocol_name=protocol_title,
            use_pip=self.use_pip,
            timeline=self.timeline,
            events=self.events,
            tasks=self.tasks,
            inversion_ticks=inversion_ticks,
            total_ticks=self.current_tick,
        )


# ==============================================================================
# 3. TERMINAL VISUALIZER (GANTT CHART, CPU TIMELINE, METRICS)
# ==============================================================================

def print_banner():
    print("=" * 88)
    print("   REAL-TIME OPERATING SYSTEM (RTOS) — PRIORITY INHERITANCE PROTOCOL (PIP) SIMULATOR")
    print("   Embedded & Real-Time Systems Academic Research Project | Pure Python Engine")
    print("=" * 88)


def print_task_specifications(task_specs: List[TaskSpec]):
    print("\n┌──────────────────────────────────────────────────────────────────────────────────────┐")
    print("│                          1. INPUT TASK SET SPECIFICATIONS                            │")
    print("├──────────┬──────────────┬───────────────┬──────────────┬─────────────────────────────┤")
    print("│ Task ID  │ Arrival Time │ Base Priority │ Total Burst  │ Execution Phases (Burst/CS) │")
    print("├──────────┼──────────────┼───────────────┼──────────────┼─────────────────────────────┤")
    for spec in sorted(task_specs, key=lambda x: -x.base_priority):
        phases_str = " -> ".join(
            f"Lock({p.resource}):{p.duration}s" if p.resource else f"CPU:{p.duration}s"
            for p in spec.phases
        )
        print(
            f"│ {spec.name:<8} │ t = {spec.arrival_time:<8} │ {spec.base_priority:<13} │ "
            f"{spec.total_burst:<10}s │ {phases_str:<27} │"
        )
    print("└──────────┴──────────────┴───────────────┴──────────────┴─────────────────────────────┘")
    print("  * Note: Higher Priority Number = Higher Urgency (e.g., 3 = High, 2 = Medium, 1 = Low)")


def render_gantt_and_timeline(result: SimulationResult, task_specs: List[TaskSpec]):
    """Renders a clean ASCII/Unicode Gantt Chart, Resource Chart, and CPU Timeline."""
    total_t = result.total_ticks
    sorted_specs = sorted(task_specs, key=lambda x: -x.base_priority)

    print("\n" + "━" * 88)
    print(f"  SIMULATION MODE: {result.protocol_name}")
    print("━" * 88)

    print("\n  [Gantt Chart Legend]:")
    print("    ███ : Normal CPU Execution        ▓▓▓ : Critical Section (Mutex Locked)")
    print("    ▲▲▲ : Running w/ Inherited Prio   ░░░ : Blocked (Waiting for Mutex)")
    print("    ··· : Ready Queue (Preempted)     ─── : Not Arrived / Completed\n")

    header_ticks = "  Time (t) │" + "".join(f"{t:>3} " for t in range(total_t))
    divider_line = "  ─────────┼" + "────" * total_t
    print(header_ticks)
    print(divider_line)

    symbol_map = {
        "RUN_CPU": "███|",
        "RUN_CS":  "▓▓▓|",
        "RUN_INH": "▲▲▲|",
        "BLOCKED": "░░░|",
        "READY":   "···|",
        "DONE":    "   |",
        "NONE":    "   |",
    }

    for spec in sorted_specs:
        row_cells = []
        for rec in result.timeline:
            st = rec.task_states.get(spec.name, "NONE")
            row_cells.append(symbol_map.get(st, "   |"))
        prio_tag = f"{spec.name}(P{spec.base_priority})"
        print(f"  {prio_tag:<9}│" + "".join(row_cells))

    print(divider_line)

    cpu_cells = []
    for rec in result.timeline:
        if rec.running_task:
            short_name = rec.running_task[:3]
            cpu_cells.append(f"{short_name:>3}|")
        else:
            cpu_cells.append("IDL|")
    print("  CPU Core │" + "".join(cpu_cells))

    prio_cells = []
    for rec in result.timeline:
        if rec.effective_prio is not None:
            marker = f"*{rec.effective_prio}" if rec.is_inherited else f"P{rec.effective_prio}"
            prio_cells.append(f"{marker:>3}|")
        else:
            prio_cells.append("  -|")
    print("  Eff.Prio │" + "".join(prio_cells) + "  (* = Inherited Priority)")

    if result.timeline and result.timeline[0].resource_owners:
        for res_name in result.timeline[0].resource_owners.keys():
            res_cells = []
            for rec in result.timeline:
                owner = rec.resource_owners.get(res_name)
                res_cells.append(f"{owner[:3]:>3}|" if owner else "  -|")
            print(f"  Mutex {res_name:<2} │" + "".join(res_cells))

    inv_cells = []
    for rec in result.timeline:
        inv_cells.append(" !!|" if rec.priority_inversion_active else "   |")
    print("  Inversion│" + "".join(inv_cells) + "  (!! = Unbounded Priority Inversion)")
    print(divider_line)

    print("\n  [Kernel Event & Synchronization Log]:")
    for tick, msg in result.events:
        print(f"    t = {tick:>2}s : {msg}")

    print("\n  [Real-Time Performance & Scheduling Metrics]:")
    print("  ┌──────────┬─────────┬─────────┬────────────┬──────────────┬───────────────┬───────────────┐")
    print("  │ Task ID  │ Arrival │ Finish  │ Turnaround │ Response Time│ Ready Wait(s) │ Blocked (CS)  │")
    print("  ├──────────┼─────────┼─────────┼────────────┼──────────────┼───────────────┼───────────────┤")
    for spec in sorted_specs:
        tk = result.tasks[spec.name]
        comp = tk.completion_time if tk.completion_time is not None else -1
        turnaround = comp - spec.arrival_time if comp != -1 else -1
        first_run = tk.first_start_time - spec.arrival_time if tk.first_start_time is not None else -1
        print(
            f"  │ {spec.name:<8} │ {spec.arrival_time:>6}s │ {comp:>6}s │ "
            f"{turnaround:>9}s │ {first_run:>11}s │ {tk.ready_wait_ticks:>12}s │ {tk.blocked_ticks:>12}s │"
        )
    print("  └──────────┴─────────┴─────────┴────────────┴──────────────┴───────────────┴───────────────┘")
    print(f"  >> Total Unbounded Priority Inversion Duration: {result.inversion_ticks} ticks (seconds)")


def print_comparative_summary(res_no_pip: SimulationResult, res_with_pip: SimulationResult, task_specs: List[TaskSpec]):
    """Prints an executive side-by-side comparison of Without PIP vs With PIP."""
    highest_spec = max(task_specs, key=lambda s: s.base_priority)
    h_name = highest_spec.name

    t_no_pip = res_no_pip.tasks[h_name]
    t_with_pip = res_with_pip.tasks[h_name]

    tat_no = (t_no_pip.completion_time or 0) - highest_spec.arrival_time
    tat_with = (t_with_pip.completion_time or 0) - highest_spec.arrival_time
    saved = tat_no - tat_with
    pct = (saved / tat_no * 100.0) if tat_no > 0 else 0.0

    print("\n" + "=" * 88)
    print("                     EXECUTIVE COMPARISON SUMMARY (WITHOUT PIP vs. WITH PIP)")
    print("=" * 88)
    print(f"  • Highest-Priority Critical Task          : {h_name} (Base Priority = {highest_spec.base_priority})")
    print(f"  • {h_name} Completion Time (Without PIP)     : t = {t_no_pip.completion_time}s (Turnaround = {tat_no}s)")
    print(f"  • {h_name} Completion Time (With PIP)        : t = {t_with_pip.completion_time}s (Turnaround = {tat_with}s)")
    print(f"  • Critical Task Execution Speedup         : {saved}s faster ({pct:.1f}% reduction in turnaround time)")
    print(f"  • Unbounded Priority Inversion (No PIP)   : {res_no_pip.inversion_ticks}s (Medium tasks preempted lock holder)")
    print(f"  • Unbounded Priority Inversion (With PIP) : {res_with_pip.inversion_ticks}s (Eliminated via Priority Inheritance!)")
    print("=" * 88 + "\n")


# ==============================================================================
# 4. ZERO-DEPENDENCY HTML/SVG GANTT CHART GENERATOR
# ==============================================================================

def export_html_gantt_report(
    res_no_pip: SimulationResult,
    res_with_pip: SimulationResult,
    task_specs: List[TaskSpec],
    filename: str = "pip_gantt_report.html"
):
    """Generates a standalone HTML visual report with Gantt charts and CPU timelines."""
    sorted_specs = sorted(task_specs, key=lambda x: -x.base_priority)

    def build_gantt_section(res: SimulationResult) -> str:
        total_t = res.total_ticks
        headers = "".join(f"<th>{t}-{t+1}</th>" for t in range(total_t))
        rows_html = ""

        color_map = {
            "RUN_CPU": ("#3b82f6", "CPU"),
            "RUN_CS":  ("#2563eb", "Lock"),
            "RUN_INH": ("#f59e0b", "PIP Boost"),
            "BLOCKED": ("#ef4444", "Blocked"),
            "READY":   ("#e2e8f0", "Ready"),
            "DONE":    ("#f8fafc", ""),
            "NONE":    ("#f8fafc", ""),
        }

        for spec in sorted_specs:
            cells = ""
            for rec in res.timeline:
                st = rec.task_states.get(spec.name, "NONE")
                bg, label = color_map.get(st, ("#ffffff", ""))
                text_color = "#ffffff" if st in ("RUN_CPU", "RUN_CS", "RUN_INH", "BLOCKED") else "#64748b"
                cells += (
                    f'<td style="background:{bg}; color:{text_color}; font-size:11px; '
                    f'font-weight:600; text-align:center; padding:8px 2px; border:1px solid #cbd5e1;">'
                    f'{label}</td>'
                )
            rows_html += (
                f"<tr><td style='font-weight:bold; padding:8px; border:1px solid #cbd5e1; "
                f"background:#f1f5f9;'>{spec.name} (P{spec.base_priority})</td>{cells}</tr>"
            )

        inv_cells = ""
        for rec in res.timeline:
            if rec.priority_inversion_active:
                inv_cells += '<td style="background:#dc2626; color:white; text-align:center; font-size:11px; font-weight:bold;">INVERSION</td>'
            else:
                inv_cells += '<td style="background:#f0fdf4; color:#16a34a; text-align:center; font-size:11px;">OK</td>'
        rows_html += f"<tr><td style='font-weight:bold; padding:8px; border:1px solid #cbd5e1; background:#fef2f2;'>Inversion Check</td>{inv_cells}</tr>"

        return f"""
        <div class="card">
            <h2>{res.protocol_name}</h2>
            <p><strong>Unbounded Priority Inversion Duration:</strong> {res.inversion_ticks} ticks</p>
            <div style="overflow-x:auto;">
                <table style="border-collapse:collapse; width:100%; min-width:700px;">
                    <thead>
                        <tr style="background:#1e293b; color:white;">
                            <th style="padding:8px; text-align:left;">Task / Metric</th>
                            {headers}
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>
        </div>
        """

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>PIP RTOS Scheduling & Gantt Chart Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f8fafc; color: #0f172a; margin: 24px; }}
        h1 {{ color: #1e293b; border-bottom: 2px solid #cbd5e1; padding-bottom: 10px; }}
        .card {{ background: white; border-radius: 8px; padding: 20px; margin-bottom: 24px; box-shadow: 0 2px 6px rgba(0,0,0,0.08); }}
        .legend {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 20px; font-size: 13px; }}
        .badge {{ display: inline-block; width: 16px; height: 16px; border-radius: 3px; vertical-align: middle; margin-right: 6px; }}
    </style>
</head>
<body>
    <h1>RTOS Priority Inheritance Protocol (PIP) — Visual Gantt Comparison</h1>
    <div class="legend">
        <div><span class="badge" style="background:#3b82f6;"></span>Normal CPU Execution</div>
        <div><span class="badge" style="background:#2563eb;"></span>Critical Section (Mutex Locked)</div>
        <div><span class="badge" style="background:#f59e0b;"></span>Inherited Priority Execution (PIP Boost)</div>
        <div><span class="badge" style="background:#ef4444;"></span>Blocked on Mutex</div>
        <div><span class="badge" style="background:#e2e8f0;"></span>Ready / Preempted</div>
    </div>
    {build_gantt_section(res_no_pip)}
    {build_gantt_section(res_with_pip)}
</body>
</html>
"""
    filepath = os.path.join(os.getcwd(), filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"  [HTML EXPORT] Visual Gantt Chart saved to: {filepath}")
    print("                (Double-click this file to open the graphic chart in any browser!)\n")


# ==============================================================================
# 5. PRESET SCENARIOS & INTERACTIVE USER INPUT
# ==============================================================================

def get_classic_mars_pathfinder_scenario() -> List[TaskSpec]:
    return [
        TaskSpec(
            name="T_High",
            arrival_time=2,
            base_priority=3,
            phases=[Phase(None, 1), Phase("R1", 2), Phase(None, 1)],
        ),
        TaskSpec(
            name="T_Med",
            arrival_time=4,
            base_priority=2,
            phases=[Phase(None, 5)],
        ),
        TaskSpec(
            name="T_Low",
            arrival_time=0,
            base_priority=1,
            phases=[Phase(None, 1), Phase("R1", 4), Phase(None, 1)],
        ),
    ]


def get_multi_resource_scenario() -> List[TaskSpec]:
    return [
        TaskSpec(
            name="T_High",
            arrival_time=3,
            base_priority=4,
            phases=[Phase(None, 1), Phase("R2", 2), Phase(None, 1)],
        ),
        TaskSpec(
            name="T_MedH",
            arrival_time=5,
            base_priority=3,
            phases=[Phase(None, 4)],
        ),
        TaskSpec(
            name="T_MedL",
            arrival_time=1,
            base_priority=2,
            phases=[Phase("R2", 2), Phase("R1", 2), Phase(None, 1)],
        ),
        TaskSpec(
            name="T_Low",
            arrival_time=0,
            base_priority=1,
            phases=[Phase("R1", 3), Phase(None, 1)],
        ),
    ]


def get_custom_user_scenario() -> List[TaskSpec]:
    print("\n--- CUSTOM TASK SET CONFIGURATION ---")
    while True:
        try:
            num_tasks = int(input("Enter number of tasks (e.g., 3): ").strip())
            if num_tasks > 0:
                break
        except ValueError:
            pass
        print("Please enter a valid positive integer.")

    specs: List[TaskSpec] = []
    for i in range(num_tasks):
        print(f"\n[Configuring Task #{i+1}]")
        name = input(f"  Task Name (default: T{i+1}): ").strip() or f"T{i+1}"
        arrival = int(input(f"  Arrival Time for {name} (e.g., 0, 2, 4): ").strip() or "0")
        prio = int(input(f"  Base Priority for {name} (higher = more urgent, e.g., 1, 2, 3): ").strip() or str(i + 1))

        print(f"  Enter execution phases for {name}.")
        print("  Format: comma-separated items like  CPU:1, R1:4, CPU:1  (where R1 is a mutex name)")
        raw_phases = input("  Phases: ").strip()
        phases: List[Phase] = []
        if not raw_phases:
            phases.append(Phase(None, 3))
        else:
            for item in raw_phases.split(","):
                parts = item.strip().split(":")
                if len(parts) == 2:
                    p_type, dur_str = parts[0].strip(), parts[1].strip()
                    res = None if p_type.upper() == "CPU" else p_type.upper()
                    phases.append(Phase(res, max(1, int(dur_str))))
                else:
                    phases.append(Phase(None, 2))

        specs.append(TaskSpec(name=name, arrival_time=arrival, base_priority=prio, phases=phases))

    return specs


def run_selected_scenario(task_specs: List[TaskSpec]):
    print_task_specifications(task_specs)

    sim_no_pip = RTOSSimulator(task_specs, use_pip=False)
    res_no_pip = sim_no_pip.run()
    render_gantt_and_timeline(res_no_pip, task_specs)

    sim_with_pip = RTOSSimulator(task_specs, use_pip=True)
    res_with_pip = sim_with_pip.run()
    render_gantt_and_timeline(res_with_pip, task_specs)

    print_comparative_summary(res_no_pip, res_with_pip, task_specs)
    export_html_gantt_report(res_no_pip, res_with_pip, task_specs)


def main():
    print_banner()
    print("\nSelect Simulation Mode:")
    print("  [1] Classic 3-Task Scenario (Mars Pathfinder Priority Inversion vs. PIP) [Default]")
    print("  [2] Advanced 4-Task Chained Inheritance Scenario (2 Shared Mutexes: R1, R2)")
    print("  [3] Custom Interactive Input (Define your own tasks, priorities, and locks)")

    try:
        choice = input("\nEnter choice (1/2/3) [Press Enter for 1]: ").strip()
    except EOFError:
        choice = "1"

    if choice == "2":
        specs = get_multi_resource_scenario()
    elif choice == "3":
        specs = get_custom_user_scenario()
    else:
        specs = get_classic_mars_pathfinder_scenario()

    run_selected_scenario(specs)


if __name__ == "__main__":
    main()