# Priority Inheritance Protocol (PIP) — RTOS Scheduler Simulator
### شبیه‌ساز پروتکل وراثت اولویت (PIP) در سیستم‌های عامل بی‌درنگ

![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)
![Dependencies](https://img.shields.io/badge/Dependencies-None%20(Pure%20Python)-brightgreen.svg)
![Domain](https://img.shields.io/badge/Course-Embedded%20%26%20Real--Time%20Systems-orange.svg)
![License](https://img.shields.io/badge/License-MIT-lightgrey.svg)

**[🇬🇧 English Documentation](#english-documentation) | [🇮🇷 مستندات فارسی](#مستندات-فارسی)**

---

<a name="english-documentation"></a>
## 🇬🇧 English Documentation

### 1. Overview
In **Real-Time Operating Systems (RTOS)** and embedded systems, tasks with strict timing constraints often share critical resources (such as I/O buses, shared memory, or sensors) protected by mutual exclusion locks (**Mutexes / Binary Semaphores**).

When a high-priority task is forced to wait for a lower-priority task to release a shared resource, and that lower-priority task is simultaneously preempted by one or more medium-priority tasks, **Unbounded Priority Inversion** occurs. This phenomenon famously caused the **1997 Mars Pathfinder** spacecraft to experience repeated system resets on the surface of Mars.

This repository provides a **zero-dependency, discrete-time RTOS kernel simulator** in Python that models, compares, and visualizes:
1. **Standard Preemptive Priority Scheduling (Without PIP)** — demonstrating unbounded Priority Inversion.
2. **Priority Inheritance Protocol (With PIP)** — demonstrating dynamic priority promotion, bounded blocking times, and real-time guarantee preservation.

---

### 2. Theoretical Background

#### 2.1. The Priority Inversion Problem
Suppose three tasks exist in a preemptive priority-driven RTOS where priority orders are $\text{Priority}(T_{High}) > \text{Priority}(T_{Med}) > \text{Priority}(T_{Low})$:
1. $T_{Low}$ arrives first and locks shared mutex `R1`.
2. $T_{High}$ arrives, preempts $T_{Low}$, and soon requests mutex `R1`. Because `R1` is held by $T_{Low}$, $T_{High}$ transitions to the **BLOCKED** state.
3. $T_{Med}$ arrives (which does not need `R1` at all). Because $\text{Priority}(T_{Med}) > \text{Priority}(T_{Low})$, $T_{Med}$ preempts $T_{Low}$ and executes to completion.
4. **Result:** $T_{High}$ is indirectly preempted by a lower-priority task ($T_{Med}$) for an unpredictable duration.

#### 2.2. How Priority Inheritance Protocol (PIP) Solves It
Proposed by *Sha, Rajkumar, and Lehoczky (1990)*, **PIP** distinguishes between a task's static **Base Priority** ($P_{base}$) and its dynamic **Effective Priority** ($P_{eff}$):

$$P_{eff}(T_i) = \max \left( P_{base}(T_i), \; \max_{T_k \in \text{BlockedBy}(T_i)} P_{eff}(T_k) \right)$$

* **Inheritance Rule:** When $T_{High}$ blocks on resource `R1` held by $T_{Low}$, $T_{Low}$ temporarily inherits $T_{High}$'s priority ($P_{eff}(T_{Low}) \leftarrow P_{eff}(T_{High})$). Consequently, arriving medium-priority tasks ($T_{Med}$) **cannot preempt** $T_{Low}$.
* **Transitivity:** If $T_{High}$ blocks on $T_{Med}$, and $T_{Med}$ blocks on $T_{Low}$, then $T_{Low}$ transitively inherits $T_{High}$'s priority.
* **Restoration Rule:** As soon as $T_{Low}$ releases `R1`, its priority reverts to its original base value ($P_{base}(T_{Low})$), and $T_{High}$ is immediately unblocked and scheduled on the CPU.

---

### 3. Key Features of This Simulator
* **Zero External Dependencies:** Built 100% with the Python 3 standard library (`dataclasses`, `typing`, `copy`). Runs out-of-the-box on any machine.
* **Terminal ASCII/Unicode Gantt Chart & CPU Timeline:** Visualizes tick-by-tick task states (`RUN_CPU`, `RUN_CS`, `RUN_INH`, `BLOCKED`, `READY`), active effective priorities, mutex lock owners, and Priority Inversion warning markers.
* **Automatic HTML Visual Dashboard Export:** Automatically generates `pip_gantt_report.html` after every run for high-resolution browser viewing and academic presentations.
* **Interactive & Preset Modes:** Includes the classic 3-task Mars Pathfinder scenario, a 4-task chained multi-resource scenario, and a full interactive CLI for custom user processes.

---

### 4. Sample Output (Classic 3-Task Scenario)

```text
  SIMULATION MODE: Standard Priority Scheduling (WITHOUT PIP)
  Time (t) │  0   1   2   3   4   5   6   7   8   9  10  11  12  13 
  ─────────┼────────────────────────────────────────────────────────
  T_High(P3│   |   |███|░░░|░░░|░░░|░░░|░░░|░░░|░░░|░░░|▓▓▓|▓▓▓|███|
  T_Med(P2)│   |   |   |   |███|███|███|███|███|   |   |   |   |   |
  T_Low(P1)│███|▓▓▓|···|▓▓▓|···|···|···|···|···|▓▓▓|▓▓▓|···|···|···|
  ─────────┼────────────────────────────────────────────────────────
  CPU Core │T_L|T_L|T_H|T_L|T_M|T_M|T_M|T_M|T_M|T_L|T_L|T_H|T_H|T_H|
  Eff.Prio │ P1| P1| P3| P1| P2| P2| P2| P2| P2| P1| P1| P3| P3| P3|
  Mutex R1 │  -|T_L|T_L|T_L|T_L|T_L|T_L|T_L|T_L|T_L|T_L|T_H|T_H|  -|
  Inversion│   |   |   |   | !!| !!| !!| !!| !!|   |   |   |   |   |
```

```text
  SIMULATION MODE: Priority Inheritance Protocol (WITH PIP)
  Time (t) │  0   1   2   3   4   5   6   7   8   9  10  11  12  13  14 
  ─────────┼────────────────────────────────────────────────────────────
  T_High(P3│   |   |███|░░░|░░░|░░░|▓▓▓|▓▓▓|███|   |   |   |   |   |   |
  T_Med(P2)│   |   |   |   |···|···|···|···|···|███|███|███|███|███|   |
  T_Low(P1)│███|▓▓▓|···|⏫▓|⏫▓|⏫▓|···|···|···|···|···|···|···|···|███|
  ─────────┼────────────────────────────────────────────────────────────
  CPU Core │T_L|T_L|T_H|T_L|T_L|T_L|T_H|T_H|T_H|T_M|T_M|T_M|T_M|T_M|T_L|
  Eff.Prio │ P1| P1| P3| *3| *3| *3| P3| P3| P3| P2| P2| P2| P2| P2| P1|
  Mutex R1 │  -|T_L|T_L|T_L|T_L|T_L|T_H|T_H|  -|  -|  -|  -|  -|  -|  -|
  Inversion│   |   |   |   |   |   |   |   |   |   |   |   |   |   |   |
```

### 5. How to Run
```bash
git clone [https://github.com/YOUR_USERNAME/rtos-priority-inheritance-simulator.git](https://github.com/YOUR_USERNAME/rtos-priority-inheritance-simulator.git)
cd rtos-priority-inheritance-simulator
python pip_simulator.py
```

---
---

<a name="مستندات-فارسی"></a>
## 🇮🇷 مستندات فارسی

### ۱. معرفی پروژه
در **سیستم‌های نهفته و بی‌درنگ (Embedded and Real-Time Systems)**، وظایف (Tasks) مختلف بر اساس میزان اهمیت و ضرب‌الاجل خود دارای **اولویت (Priority)** هستند. زمانی که چند پردازش به یک منبع مشترک (مانند باس ارتباطی، حافظه مشترک یا سنسور) نیاز داشته باشند، از قفل‌های انحصار متقابل (**Mutex**) استفاده می‌شود.

اگر یک پردازش با اولویت بالا ($T_{High}$) منتظر آزاد شدن منبعی بماند که در اختیار پردازش با اولویت پایین ($T_{Low}$) است، و در همین حین یک پردازش با اولویت متوسط ($T_{Med}$) وارد شود و پردازنده را از $T_{Low}$ بگیرد، پدیده خطرناک **وارونگی اولویت (Priority Inversion)** رخ می‌دهد. در این حالت، پردازش حیاتی سیستم عملاً معطل پردازشی با اولویت متوسط می‌ماند که هیچ ربطی به منبع مشترک ندارد! (مشابه باگ معروف فضاپیمای **Mars Pathfinder** در سال ۱۹۹۷).

این پروژه یک شبیه‌ساز هسته زمان‌بند بی‌درنگ با **پایتون خالص (بدون هیچ کتابخانه جانبی)** است که رفتار سیستم را در دو حالت **بدون پروتکل (وقوع وارونگی اولویت)** و **مجهز به پروتکل وراثت اولویت (PIP)** شبیه‌سازی، مقایسه و به صورت گانت‌چارت (Gantt Chart) ترسیم می‌کند.

---

### ۲. منطق عملکرد پروتکل وراثت اولویت (PIP)
پروتکل **Priority Inheritance Protocol (PIP)** برای هر پردازش دو نوع اولویت تعریف می‌کند:
1. **اولویت پایه (Base Priority - $P_{base}$):** اولویت ثابتی که در ابتدای تعریف پردازش به آن داده شده است.
2. **اولویت مؤثر یا فعلی (Effective Priority - $P_{eff}$):** اولویتی که زمان‌بند سیستم‌عامل در هر لحظه بر اساس آن تصمیم می‌گیرد.

#### قوانین چهارگانه الگوریتم در این شبیه‌ساز:
1. **قانون زمان‌بندی (Scheduling Rule):** پردازنده همیشه به پردازشِ آماده (Ready) تعلق می‌گیرد که بالاترین **اولویت مؤثر ($P_{eff}$)** را داشته باشد.
2. **قانون تخصیص منبع (Allocation Rule):** اگر پردازش در حال اجرا به منبع `R` نیاز داشته باشد و منبع آزاد باشد، قفل آن را دریافت می‌کند؛ در غیر این صورت به حالت **مسدود (Blocked)** می‌رود.
3. **قانون وراثت اولویت (Priority Inheritance Rule):** هرگاه پردازش $T_{High}$ به دلیل قفل بودن منبع `R` توسط $T_{Low}$ مسدود شود، پردازش $T_{Low}$ موقتاً اولویت پردازش $T_{High}$ را به ارث می‌برد:
   $$P_{eff}(T_{Low}) = \max(P_{eff}(T_{Low}), P_{eff}(T_{High}))$$
   به این ترتیب، اگر پردازش با اولویت متوسط ($T_{Med}$) وارد سیستم شود، دیگر زورش به $T_{Low}$ نمی‌رسد و $T_{Low}$ می‌تواند به سرعت ناحیه بحرانی خود را تمام کرده و منبع را آزاد کند.
4. **قانون بازگشت اولویت (Priority Restoration Rule):** به محض اینکه $T_{Low}$ منبع `R` را آزاد کند، اولویت مؤثر آن به اولویت پایه اولیه‌اش برمی‌گردد و بلافاصله پردازش منتظر ($T_{High}$) بیدار شده و پردازنده را در اختیار می‌گیرد.

---

### ۳. امکانات و خروجی‌های شبیه‌ساز
* **رسم گانت‌چارت (Gantt Chart) در ترمینال:** نمایش وضعیت لحظه‌به‌لحظه هر پردازش با تفکیک اجرای عادی (`███`)، اجرای ناحیه بحرانی (`▓▓▓`)، اجرا با اولویت به ارث رسیده (`⏫▓`)، مسدود شده روی منبع (`░░░`) و منتظر در صف آماده (`···`).
* **نوار زمان پردازنده (CPU Timeline) و مالکیت منابع:** نمایش اینکه در هر ثانیه کدام پردازش روی CPU است، اولویت فعلی چیست و کدام پردازش قفل منبع `R1` یا `R2` را در دست دارد.
* **لاگ دقیق رویدادهای هسته (Kernel Event Log):** ثبت لحظه ورود، قفل شدن، مسدود شدن، ارتقای اولویت (PIP Boost) و بازگشت اولویت.
* **جدول متریک‌های عملکردی:** محاسبه دقیق Turnaround Time، Response Time، زمان انتظار و مدت زمان وقوع Priority Inversion.
* **تولید خودکار گزارش گرافیکی تحت وب (`pip_gantt_report.html`):** پس از هر بار اجرا، یک فایل HTML مستقل بدون نیاز به اینترنت یا کتابخانه جانبی ساخته می‌شود که گانت‌چارت رنگی را در مرورگر نمایش می‌دهد.
* **قابلیت دریافت ورودی دلخواه:** امکان تعریف پردازش‌های دلخواه، زمان ورود، اولویت و توالی قفل منابع توسط کاربر در ترمینال.

---

### ۴. نحوه اجرا
نیاز به نصب هیچ کتابخانه‌ای نیست. کافیست پایتون ۳ روی سیستم شما نصب باشد:

```bash
python pip_simulator.py
```

پس از اجرا، منوی زیر نمایش داده می‌شود:
1. **گزینه ۱:** اجرای سناریوی کلاسیک ۳ پردازشی (مقایسه دقیق رخداد Priority Inversion و حل آن با PIP).
2. **گزینه ۲:** اجرای سناریوی پیشرفته ۴ پردازشی با ۲ منبع مشترک (`R1` و `R2`) و وراثت زنجیره‌ای.
3. **گزینه ۳:** وارد کردن دستی پردازش‌ها و منابع دلخواه توسط شما.