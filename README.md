# Work Timer Plugin

A smart work time tracker for Krita that measures your document's actual working time by including time spent thinking/researching via user feedback.

<img width="526" height="143" alt="2025-12-28 10-14-39" src="https://github.com/user-attachments/assets/cc2c40ee-51e9-4e44-a5bd-719d4f704242" />


### Why not just look at Document Information?

Only Krita's *.kra* file type supports "Total editing time" tracking and simply tracking brushstrokes is not an accurate way to measure time spent on creative work anyways. When working on a project, you may be planning, researching, or gathering references while the file is open. A typical time tracker cannot account for this, because it only measures direct activity. This plugin addresses that limitation by asking you whether periods of inactivity should count as idle time or as productive thinking and research time. The more you respond to its prompts, the more the plugin learns from your choices and reduces how often it prompts you.

### Plugin Features

- Automatically tracks time spent actively working on your document

- Accounts for time away from the file (thinking, planning, researching) through simple user prompts

- Learns from your responses to reduce interruptions over time

- Tracks time before a file is even saved (don't have to save files to start tracking time)

- Saves work time per file and restores it when reopening

- Preserves tracked time when image files are moved or renamed

- Imports existing editing time from Krita .kra files

- Works in the background without requiring the docker to stay open

## Installation

**Download the plugin:**
>Scroll up and click the green "Code" button, click  "Download ZIP" option
 
**Open Krita and in the top bar click:**
>**Tools  > Scripts > Import Python Plugin From File >** select the zip file

**Restart Krita:**
>Close and open Krita

*Same steps for Updating*

---

## How It Works

### Automatic Tracking

When you draw, edit, or navigate your canvas, the timer counts. When you stop interacting, it pauses (after a short buffer) to avoid counting breaks. You don't need to have the **Work Timer** docker open since the plugin is also an extension. If the plugin is enabled, it will automatically track your document work time.

### What Gets Tracked

- Mouse clicks and drags on canvas  
- Keyboard shortcuts and input  
- Pen and tablet strokes  
- Canvas navigation (zoom, pan)

### Timer States

| State                  | Meaning                                      |
|------------------------|----------------------------------------------|
| **Tracking**           | Actively counting work time (saved file)     |
| **Tracking (unsaved)** | Counting work time for an unsaved file       |
| **Paused**             | No activity detected, timer paused           |
| **No document**        | No document is open                          |

**Unsaved Document Tracking:**  
The timer tracks your work even before you save. When you save the document, all accumulated time is automatically transferred to the saved file. If you close without saving, the time is discarded.


## Tracked Time Persistence

### Per-File Time Tracking

Your work time is saved for each individual file and persists across sessions. When you reopen a file, your accumulated work time is automatically restored.

### How Files Are Identified

| File Type                | Identification Method               | Survives                          |
|--------------------------|-------------------------------------|-----------------------------------|
| **.kra**          | Document UUID (embedded in file)    | Renames, moves, and copies        |
| **.png, .jpg, .psd, etc.** | Content fingerprint + path         | Moves, renames (if content unchanged) |

### Move Detection for Image Files

When you move or rename a .png, .jpg, or other image file, the plugin can detect this and preserve your work time. It creates a **content fingerprint** based on:

- Image dimensions (width × height)  
- File size  
- A sample of the image content  

When you open a file at a new location, the plugin checks if it matches a previously tracked file and automatically migrates your work time.

**Note:**  
Move detection works as long as you haven't edited the file since the last save. If you edit and save the file after moving it, the fingerprint will change and the connection to the old record may be lost.

### Importing Time from Krita Files

When you open a *.kra* file for the first time with the plugin, it reads the file's built-in **Total editing time** metadata. If this time exceeds 1 minute, then that time is used as a starting point after being adjusted slightly upward to account for thinking time between brushstrokes.

**Technical Note:**  
The adjustment uses a logarithmic formula that applies a higher multiplier to short sessions (~1.4x for 2-minute sessions) and a lower multiplier to long sessions (~1.2x for 2-hour sessions). This accounts for the fact that planning and thinking are proportionally higher at the start of a project.


## User Feedback and Prediction

### The Prompt Dialog

When you return after a pause, the plugin may ask you to state if you were thinking about your project. The dialog shows:

<img width="341" height="161" alt="2025-12-28 10-48-19" src="https://github.com/user-attachments/assets/520ed679-be66-48aa-baed-6738e1fa8192" />

- How long you were away  
- The system's confidence level (how sure it is)
- Option to respond Yes or No

### Auto-Decisions & Undo

When the plugin is confident about its assumption of the nature of your idle time, it may auto-add or auto-discard time. You'll see a brief notification with an **Undo** button if you disagree.

<img width="281" height="41" alt="2025-12-28 10-48-40" src="https://github.com/user-attachments/assets/3d77a81a-2d96-46a3-af44-95159e90514b" />


### Accuracy Indicator

The docker shows an accuracy indicator that reflects how well the plugin understands your work patterns:

| Level     | Meaning                                           |
|-----------|---------------------------------------------------|
| **Learning** | Still gathering data (prompts more often)     |
| **Medium**   | Developing understanding of your patterns     |
| **High**     | Confident in your patterns (fewer prompts)     |

*The indicator is visible if you right click the **Work Timer** docker.*

<img width="254" height="235" alt="2025-12-30 23-55-06" src="https://github.com/user-attachments/assets/3028a3cd-e0bf-493f-8ef2-bb37c13f5c3b" />

### Reset Tracked Time (v1.0.1)

<img width="342" height="154" alt="2025-12-31 00-13-50" src="https://github.com/user-attachments/assets/51724ca2-6269-4fc4-ab14-3883305e27c4" />

Under the accuracy indicator there is an option to reset your work time for the currently opened file. While a `.kra` file is open, the time is reset to the adjusted total editing time, not 0. Any other file’s work time will be reset to 0 when the reset is confirmed.
**From previous example:** The work time for the `.kra` painting will always be reset to 5 hrs 21 when Reset Tracked Time is clicked.

## Data Storage

All tracked data is stored at: <br>

 **Windows:** `%userprofile%\AppData\Roaming\Krita\work_timer_data`  <br>
 **Linux:** `~/.local/share/krita/work_timer_data` <br>

The `.json` file in that folder contains:

- Work time for each tracked file  
- Your learning profile (patterns the plugin has learned)  


## Tips

- You can press **Y** to reply yes, or **N** / **Esc** to reply no to the prompt dialog.  
- Answer prompts honestly to improve the tracker's accuracy  
- To preserve your work time for non *.kra* files, don't edit **and** rename between times you open them in Krita  


_Work Timer Plugin for Krita – Smart time tracking for artists_
