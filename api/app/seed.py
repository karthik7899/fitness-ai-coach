"""Seed the exercise catalogue.

Muscle mappings drive `v_weekly_muscle_volume`, which is how the coach reasons
about balance, so it is worth having sensible defaults on day one.

    uv run python -m app.seed
"""

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Exercise

# name, category, modality, primary muscles
CATALOGUE = [
    ("Back Squat", "Legs", "weight_reps", ["quads", "glutes"]),
    ("Front Squat", "Legs", "weight_reps", ["quads"]),
    ("Leg Press", "Legs", "weight_reps", ["quads", "glutes"]),
    ("Romanian Deadlift", "Legs", "weight_reps", ["hamstrings", "glutes"]),
    ("Deadlift", "Back", "weight_reps", ["hamstrings", "glutes", "lower_back"]),
    ("Leg Curl", "Legs", "weight_reps", ["hamstrings"]),
    ("Leg Extension", "Legs", "weight_reps", ["quads"]),
    ("Calf Raise", "Legs", "weight_reps", ["calves"]),
    ("Walking Lunge", "Legs", "weight_reps", ["quads", "glutes"]),
    ("Hip Thrust", "Legs", "weight_reps", ["glutes"]),
    ("Bodyweight Squat", "Legs", "bodyweight_reps", ["quads", "glutes"]),
    ("Glute Bridge", "Legs", "bodyweight_reps", ["glutes"]),
    ("Bench Press", "Chest", "weight_reps", ["chest", "triceps"]),
    ("Incline Bench Press", "Chest", "weight_reps", ["chest", "front_delts"]),
    ("Dumbbell Press", "Chest", "weight_reps", ["chest", "triceps"]),
    ("Chest Fly", "Chest", "weight_reps", ["chest"]),
    ("Push-Up", "Chest", "bodyweight_reps", ["chest", "triceps"]),
    ("Dip", "Chest", "weighted_bodyweight", ["chest", "triceps"]),
    ("Overhead Press", "Shoulders", "weight_reps", ["front_delts", "triceps"]),
    ("Pike Push-Up", "Shoulders", "bodyweight_reps", ["front_delts", "triceps"]),
    ("Lateral Raise", "Shoulders", "weight_reps", ["side_delts"]),
    ("Rear Delt Fly", "Shoulders", "weight_reps", ["rear_delts"]),
    ("Face Pull", "Shoulders", "weight_reps", ["rear_delts", "upper_back"]),
    ("Pull-Up", "Back", "weighted_bodyweight", ["lats", "biceps"]),
    ("Chin-Up", "Back", "weighted_bodyweight", ["lats", "biceps"]),
    ("Lat Pulldown", "Back", "weight_reps", ["lats", "biceps"]),
    ("Barbell Row", "Back", "weight_reps", ["upper_back", "lats"]),
    ("Seated Cable Row", "Back", "weight_reps", ["upper_back", "lats"]),
    ("Dumbbell Row", "Back", "weight_reps", ["lats", "upper_back"]),
    ("Barbell Curl", "Arms", "weight_reps", ["biceps"]),
    ("Dumbbell Curl", "Arms", "weight_reps", ["biceps"]),
    ("Hammer Curl", "Arms", "weight_reps", ["biceps", "forearms"]),
    ("Triceps Pushdown", "Arms", "weight_reps", ["triceps"]),
    ("Skull Crusher", "Arms", "weight_reps", ["triceps"]),
    ("Plank", "Core", "duration", ["abs"]),
    ("Hanging Leg Raise", "Core", "bodyweight_reps", ["abs"]),
    ("Cable Crunch", "Core", "weight_reps", ["abs"]),
    ("Back Extension", "Core", "bodyweight_reps", ["lower_back"]),
]


def seed() -> int:
    added = 0
    with SessionLocal() as session:
        for name, category, modality, muscles in CATALOGUE:
            exists = session.scalar(
                select(Exercise.id).where(func.lower(Exercise.name) == name.lower())
            )
            if exists:
                continue
            session.add(
                Exercise(
                    name=name,
                    category=category,
                    modality=modality,
                    primary_muscles=muscles,
                )
            )
            added += 1
        session.commit()
    return added


if __name__ == "__main__":
    print(f"Seeded {seed()} new exercises.")
