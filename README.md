# Fitness AI Coach & Gemini Integrator

A premium local Python application that aggregates your fitness data from **Strava**, **Google Fit** (syncing your Da Fit watch steps and sleep), and **FitNotes** (syncing your strength workout backups from Google Drive), creating a unified dashboard and a specialized **Gemini AI Coach Chat** to query your training data.

---

## Prerequisites

Make sure you have Python 3.8+ installed on your system.

---

## Step 1: Install Dependencies

Open a command prompt or terminal in this folder and run:
```bash
pip install -r requirements.txt
```

---

## Step 2: Acquire API Credentials

### 1. Google Gemini API
- Go to [Google AI Studio](https://aistudio.google.com/).
- Click **Get API Key** and generate a new key.
- Paste this key into the `.env` file under `GEMINI_API_KEY`.

### 2. Strava API
- Go to [Strava API Settings](https://www.strava.com/settings/api).
- Create an app (fill in details, set **Authorization Callback Domain** to `localhost:8501`).
- Copy the **Client ID** and **Client Secret** into the `.env` file under `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET`.

### 3. Google API (Google Drive & Google Fit)
- Go to the [Google Cloud Console](https://console.cloud.google.com/).
- Create a new project.
- Search for and enable the **Google Drive API** and the **Fitness API**.
- Go to the **OAuth consent screen** tab:
  - Select **User Type: External**.
  - Add your own email as a developer/test user.
  - Under Scopes, add the following scopes:
    - `https://www.googleapis.com/auth/drive.readonly` (To read your FitNotes backups)
    - `https://www.googleapis.com/auth/fitness.activity.read` (To read Google Fit steps/activities)
    - `https://www.googleapis.com/auth/fitness.sleep.read` (To read Google Fit sleep details)
- Go to the **Credentials** tab:
  - Click **Create Credentials** -> **OAuth client ID**.
  - Select Application type: **Desktop app**.
  - Name it "Fitness Coach App".
  - Click Create.
  - Download the JSON file and save it in the project root directory as **`credentials.json`**.

---

## Step 3: Configure FitNotes & Da Fit on Your Phone

- **Da Fit Sync**: In your phone's Da Fit app settings, go to Profile -> third-party apps, select **Google Fit**, and authorize sync to your Google Account.
- **FitNotes Sync**: In the FitNotes settings on your phone, go to **Settings -> Backup -> Cloud**, click **Google Drive**, and upload a backup (`FitNotes_Backup.fitnotes`). Alternatively, enable **Automatic Backup** to Google Drive.

---

## Step 4: Run the Application

Start the local Streamlit dashboard:
```bash
streamlit run app.py
```

Click the OAuth authentication links in the sidebar to authorize Strava and Google. Once authorized, click **Sync All Data** to populate the charts and start chatting with your Gemini Coach!
