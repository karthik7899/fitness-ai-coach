-- A Gadgetbridge export. Timestamps are epoch seconds; the fixtures pin the
-- timezone to UTC so both implementations bucket them into the same days.
--
-- 2026-09-11 00:00:00Z = 1789084800
CREATE TABLE MOYOUNG_ACTIVITY_SAMPLE (
    TIMESTAMP INTEGER NOT NULL, DEVICE_ID INTEGER NOT NULL, USER_ID INTEGER NOT NULL,
    RAW_INTENSITY INTEGER, STEPS INTEGER, RAW_KIND INTEGER, KIND INTEGER,
    HEART_RATE INTEGER, PRIMARY KEY (TIMESTAMP, DEVICE_ID, USER_ID));

-- A table that is not a sample table at all: must be ignored, not guessed at.
CREATE TABLE DEVICE (_id INTEGER PRIMARY KEY, NAME TEXT);
INSERT INTO DEVICE VALUES (1, 'Da Fit watch');

-- Day one: ten samples, 100 steps each, heart rates 50..59.
-- The 10th percentile of ten sorted values is index 1, so resting HR is 51.
INSERT INTO MOYOUNG_ACTIVITY_SAMPLE (TIMESTAMP, DEVICE_ID, USER_ID, STEPS, HEART_RATE, KIND) VALUES
    (1789084800, 1, 1, 100, 50, 1), (1789084860, 1, 1, 100, 51, 1),
    (1789084920, 1, 1, 100, 52, 1), (1789084980, 1, 1, 100, 53, 1),
    (1789085040, 1, 1, 100, 54, 1), (1789085100, 1, 1, 100, 55, 1),
    (1789085160, 1, 1, 100, 56, 1), (1789085220, 1, 1, 100, 57, 1),
    (1789085280, 1, 1, 100, 58, 1), (1789085340, 1, 1, 100, 59, 1);

-- Noise and gaps: 0 bpm means "not measured" and must not drag the estimate
-- down; a NULL step count is not a zero-step minute.
INSERT INTO MOYOUNG_ACTIVITY_SAMPLE (TIMESTAMP, DEVICE_ID, USER_ID, STEPS, HEART_RATE, KIND) VALUES
    (1789085400, 1, 1, NULL, 0, 1),
    (1789085460, 1, 1, 0, 12, 1);

-- Day two: three minutes of typed sleep (light, deep, REM) and 250 steps.
-- 2026-09-12 00:00:00Z = 1789171200
INSERT INTO MOYOUNG_ACTIVITY_SAMPLE (TIMESTAMP, DEVICE_ID, USER_ID, STEPS, HEART_RATE, KIND) VALUES
    (1789171200, 1, 1, 250, 60, 2),
    (1789171260, 1, 1, NULL, 58, 4),
    (1789171320, 1, 1, NULL, 57, 16);
