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
    ("Dumbbell Shoulder Press", "Shoulders", "weight_reps", ["front_delts", "triceps"]),
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
    ("Close-Grip Bench Press", "Arms", "weight_reps", ["triceps", "chest"]),
    ("Overhead Triceps Extension", "Arms", "weight_reps", ["triceps"]),
    ("Preacher Curl", "Arms", "weight_reps", ["biceps"]),
    ("Plank", "Core", "duration", ["abs"]),
    ("Hanging Leg Raise", "Core", "bodyweight_reps", ["abs"]),
    ("Cable Crunch", "Core", "weight_reps", ["abs"]),
    ("Back Extension", "Core", "bodyweight_reps", ["lower_back"]),
]


# Other names the same exercise goes by: FitNotes' built-in names first, then
# the common shorthand. Starting a workout uses whichever of these already
# exists rather than creating a duplicate, so an imported history carries on
# under its own name. Matching ignores case, spaces and punctuation, so
# "Pull Up", "pull-up" and "Pullup" are one name.
ALIASES: dict[str, list[str]] = {
    "Back Squat": ["Barbell Squat", "Barbell Back Squat", "Squat", "High Bar Squat"],
    "Romanian Deadlift": ["Barbell Romanian Deadlift", "Stiff-Legged Deadlift", "RDL"],
    "Deadlift": ["Barbell Deadlift", "Conventional Deadlift"],
    "Leg Press": ["Leg Press Machine", "45 Degree Leg Press"],
    "Leg Curl": ["Lying Leg Curl Machine", "Seated Leg Curl Machine", "Lying Leg Curl",
                 "Seated Leg Curl", "Hamstring Curl"],
    "Calf Raise": ["Standing Calf Raise Machine", "Seated Calf Raise Machine",
                   "Standing Calf Raise", "Seated Calf Raise"],
    "Bench Press": ["Flat Barbell Bench Press", "Barbell Bench Press", "Flat Bench Press",
                    "Bench"],
    "Incline Bench Press": ["Incline Barbell Bench Press", "Incline Bench"],
    "Dumbbell Press": ["Flat Dumbbell Bench Press", "Dumbbell Bench Press",
                       "Flat Dumbbell Press"],
    "Chest Fly": ["Flat Dumbbell Fly", "Dumbbell Fly", "Cable Crossover", "Pec Deck",
                  "Pec Fly"],
    "Dip": ["Parallel Bar Triceps Dip", "Chest Dip", "Parallel Bar Dip", "Dips"],
    "Overhead Press": ["Standing Barbell Press", "Barbell Overhead Press", "Military Press",
                       "Shoulder Press", "OHP"],
    "Dumbbell Shoulder Press": ["Seated Dumbbell Press", "Seated Dumbbell Shoulder Press",
                                "Arnold Dumbbell Press", "Arnold Press"],
    "Lateral Raise": ["Lateral Dumbbell Raise", "Dumbbell Lateral Raise", "Side Raise",
                      "Cable Lateral Raise"],
    "Rear Delt Fly": ["Rear Delt Dumbbell Raise", "Reverse Dumbbell Fly", "Reverse Fly",
                      "Reverse Pec Deck"],
    "Face Pull": ["Cable Face Pull", "Rope Face Pull"],
    "Pull-Up": ["Pull Up", "Pullup", "Wide Grip Pull Up"],
    "Chin-Up": ["Chin Up", "Chinup"],
    "Lat Pulldown": ["Lat Pull Down", "Wide Grip Lat Pulldown", "Cable Lat Pulldown"],
    "Barbell Row": ["Bent Over Barbell Row", "Bent Over Row", "Pendlay Row"],
    "Seated Cable Row": ["Seated Row", "Cable Row", "Seated Machine Row"],
    "Barbell Curl": ["EZ-Bar Curl", "EZ Bar Curl", "Standing Barbell Curl"],
    "Dumbbell Curl": ["Alternating Dumbbell Curl", "Seated Dumbbell Curl", "Bicep Curl",
                      "Biceps Curl"],
    "Hammer Curl": ["Dumbbell Hammer Curl", "Rope Hammer Curl"],
    "Preacher Curl": ["EZ-Bar Preacher Curl", "Dumbbell Preacher Curl",
                      "Machine Preacher Curl"],
    "Triceps Pushdown": ["Rope Push Down", "V-Bar Push Down", "Cable Pushdown",
                         "Tricep Pushdown", "Triceps Push Down"],
    "Skull Crusher": ["EZ-Bar Skullcrusher", "Lying Triceps Extension", "Skullcrusher"],
    "Close-Grip Bench Press": ["Close Grip Barbell Bench Press", "Close Grip Bench"],
    "Overhead Triceps Extension": ["Cable Overhead Triceps Extension",
                                   "Dumbbell Overhead Triceps Extension",
                                   "Overhead Tricep Extension"],
}


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
