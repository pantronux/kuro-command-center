import time
from datetime import date, timedelta, datetime

def get_weekly_data_original(habits, logs, year, week):
    # Calculate week start (Monday) and end (Sunday)
    jan1 = date(year, 1, 1)
    week_start = jan1 + timedelta(weeks=week - 1, days=-jan1.weekday())
    week_end = week_start + timedelta(days=6)

    # Build grid data: {habit_id: {day_offset: status}}
    grid_data = {}
    daily_totals = {i: 0 for i in range(7)}  # 0=Mon, 6=Sun
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

    for habit in habits:
        grid_data[habit['id']] = {i: 0 for i in range(7)}

    for log in logs:
        habit_id = log['habit_id']
        log_date = datetime.fromisoformat(log['log_date']).date()
        if week_start <= log_date <= week_end:
            day_offset = (log_date - week_start).days
            if habit_id in grid_data and 0 <= day_offset <= 6:
                grid_data[habit_id][day_offset] = log['status']
                if log['status'] == 1:
                    daily_totals[day_offset] = daily_totals.get(day_offset, 0) + 1

    # Calculate per-habit weekly stats
    habit_stats = []
    total_possible = len(habits) * 7
    total_completed = 0

    for habit in habits:
        habit_id = habit['id']
        completed = sum(1 for day, status in grid_data[habit_id].items() if status == 1)
        target = habit.get('target_per_week', 7)
        percentage = round((completed / target * 100), 1) if target > 0 else 0
        total_completed += completed

        habit_stats.append({
            "id": habit_id,
            "title": habit['title'],
            "category": habit['category'],
            "completed": completed,
            "target": target,
            "percentage": min(percentage, 100),
            "daily_log": grid_data[habit_id]
        })

    overall_percentage = round((total_completed / total_possible * 100), 1) if total_possible > 0 else 0

    return {
        "year": year,
        "week": week,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "day_names": day_names,
        "habits": habit_stats,
        "daily_totals": daily_totals,
        "overall_stats": {
            "total_possible": total_possible,
            "total_completed": total_completed,
            "overall_percentage": overall_percentage
        }
    }

def get_weekly_data_optimized(habits, logs, year, week):
    # Calculate week start (Monday) and end (Sunday)
    jan1 = date(year, 1, 1)
    week_start = jan1 + timedelta(weeks=week - 1, days=-jan1.weekday())
    week_end = week_start + timedelta(days=6)

    # Build grid data using dict comprehension
    grid_data = {habit['id']: {i: 0 for i in range(7)} for habit in habits}
    daily_totals = {i: 0 for i in range(7)}  # 0=Mon, 6=Sun
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

    for log in logs:
        habit_id = log['habit_id']
        log_date = datetime.fromisoformat(log['log_date']).date()
        # if week_start <= log_date <= week_end: # Assuming SQL filter is enough
        day_offset = (log_date - week_start).days
        if habit_id in grid_data and 0 <= day_offset <= 6:
            grid_data[habit_id][day_offset] = log['status']
            if log['status'] == 1:
                daily_totals[day_offset] += 1 # daily_totals[day_offset] is guaranteed to exist

    # Calculate per-habit weekly stats
    habit_stats = []
    total_possible = len(habits) * 7
    total_completed = 0

    for habit in habits:
        habit_id = habit['id']
        habit_grid = grid_data[habit_id]
        completed = sum(habit_grid.values()) # status is 0 or 1, so sum is count of 1s
        target = habit.get('target_per_week', 7)
        percentage = round((completed / target * 100), 1) if target > 0 else 0
        total_completed += completed

        habit_stats.append({
            "id": habit_id,
            "title": habit['title'],
            "category": habit['category'],
            "completed": completed,
            "target": target,
            "percentage": min(percentage, 100),
            "daily_log": habit_grid
        })

    overall_percentage = round((total_completed / total_possible * 100), 1) if total_possible > 0 else 0

    return {
        "year": year,
        "week": week,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "day_names": day_names,
        "habits": habit_stats,
        "daily_totals": daily_totals,
        "overall_stats": {
            "total_possible": total_possible,
            "total_completed": total_completed,
            "overall_percentage": overall_percentage
        }
    }

# Mock data
num_habits = 1000
num_logs = 5000
year = 2023
week = 40
jan1 = date(year, 1, 1)
week_start = jan1 + timedelta(weeks=week - 1, days=-jan1.weekday())

habits = [{"id": i, "title": f"Habit {i}", "category": "General", "target_per_week": 7} for i in range(num_habits)]
logs = []
for i in range(num_logs):
    log_date = week_start + timedelta(days=i % 7)
    logs.append({
        "habit_id": i % num_habits,
        "log_date": log_date.isoformat(),
        "status": 1
    })

# Warmup
get_weekly_data_original(habits, logs, year, week)
get_weekly_data_optimized(habits, logs, year, week)

# Benchmark original
start = time.time()
for _ in range(100):
    get_weekly_data_original(habits, logs, year, week)
end = time.time()
print(f"Original: {end - start:.4f}s")

# Benchmark optimized
start = time.time()
for _ in range(100):
    get_weekly_data_optimized(habits, logs, year, week)
end = time.time()
print(f"Optimized: {end - start:.4f}s")

# Verification
res_orig = get_weekly_data_original(habits, logs, year, week)
res_opt = get_weekly_data_optimized(habits, logs, year, week)
assert res_orig == res_opt, "Results differ!"
print("Verification successful!")
