import tkinter as tk
from tkinter import filedialog
import threading
import time
import sounddevice as sd
import numpy as np
from TTS.api import TTS
import queue
import soundfile as sf
import os
from deep_translator import GoogleTranslator

# Initialize Coqui TTS with a Danish model.
tts = TTS(model_name="tts_models/da/cv/vits", progress_bar=False, gpu=False)

# Global control variables
is_paused = threading.Event()
is_stopped = threading.Event()
speed_factor = 1.0  # Default speed
audio_queue = queue.Queue()
is_playing = False  # Flag to indicate if audio is currently playing

# Hover-translation variables
current_tooltip = None
last_hovered_word = ""

# GUI Setup
root = tk.Tk()
root.title("Real-time Text to Speech + Selection Translate (Danish->Russian)")
root.geometry("900x500")
root.resizable(False, False)
root.configure(bg="light blue")

# Textbox for content
text_box = tk.Text(root, bg="white", wrap="word", font=("Arial", 14))
text_box.place(x=10, y=50, width=880, height=300)

# Function to open a file
def open_file():
    file = filedialog.askopenfilename(filetypes=[("Text Files", "*.txt")])
    if file:
        with open(file, "r", encoding='utf-8') as f:
            text = f.read()
            text_box.delete("1.0", tk.END)
            text_box.insert("1.0", text)
    print("Opened file:", file)

open_button = tk.Button(root, text="Open File", command=open_file, bg="white", font=("Arial", 12))
open_button.place(x=10, y=10)

# --- SELECTION-BASED TRANSLATION LOGIC ---
def translate_selection():
    """
    Translates the currently selected text in the text box.
    """
    try:
        selected_text = text_box.get(tk.SEL_FIRST, tk.SEL_LAST)
        translation = translate_phrase(selected_text)
        if translation:
            show_tooltip_selection(translation)
    except tk.TclError:
        print("No text selected.")

def translate_phrase(phrase):
    """
    Translate from Danish (da) to Russian (ru).
    """
    try:
        translator = GoogleTranslator(source='da', target='ru')
        translation = translator.translate(phrase)
        return translation
    except Exception as e:
        print("Translation error:", e)
        return None

def show_tooltip_selection(text):
    """
    Creates a small window near the Speak button showing the translation text.
    """
    global current_tooltip

    hide_tooltip()  # Hide the old one if it exists
    current_tooltip = tk.Toplevel(root)
    current_tooltip.wm_overrideredirect(True)
    # Position near the Speak button
    x = speak_button.winfo_rootx()
    y = speak_button.winfo_rooty() + speak_button.winfo_height() + 10
    current_tooltip.geometry(f"+{x}+{y}")

    label = tk.Label(current_tooltip, text=text, background="white", relief="solid", borderwidth=1, font=("Arial", 14))
    label.pack()

# --- HOVER-BASED TRANSLATION LOGIC ---
def on_mouse_move(event):
    """
    Called whenever the mouse moves over the text_box.
    Identifies the word under the cursor, translates it (DK->RU),
    and shows/hides a tooltip.
    """
    global last_hovered_word

    # Get the text index under mouse pointer
    idx = text_box.index(f"@{event.x},{event.y}")
    start_idx = f"{idx} wordstart"
    end_idx = f"{idx} wordend"

    try:
        word = text_box.get(start_idx, end_idx).strip()
    except tk.TclError:
        word = ""

    # If it's a new non-empty word, translate and show tooltip
    if word and word != last_hovered_word:
        last_hovered_word = word
        translation = translate_phrase(word)
        if translation:
            show_tooltip(event, f"{word} → {translation}")
    elif not word:
        hide_tooltip()

def show_tooltip(event, text):
    """
    Creates a small window near the cursor showing the translation text.
    """
    global current_tooltip

    hide_tooltip()  # Hide the old one if it exists
    current_tooltip = tk.Toplevel(root)
    current_tooltip.wm_overrideredirect(True)
    # Position near the cursor
    current_tooltip.geometry(f"+{event.x_root+20}+{event.y_root+20}")

    label = tk.Label(current_tooltip, text=text, background="white", relief="solid", borderwidth=1, font=("Arial", 14))
    label.pack()

def hide_tooltip(*args):
    """
    Destroys the tooltip window and resets last_hovered_word.
    """
    global current_tooltip, last_hovered_word
    if current_tooltip and current_tooltip.winfo_exists():
        current_tooltip.destroy()
    current_tooltip = None
    last_hovered_word = ""

# Bind the text box for hover translation
text_box.bind("<Motion>", on_mouse_move)
text_box.bind("<Leave>", hide_tooltip)

# --- TTS HIGHLIGHTING ---
def highlight_sentence(start_idx, end_idx):
    text_box.tag_remove("highlight", "1.0", tk.END)
    text_box.tag_add("highlight", start_idx, end_idx)
    text_box.tag_config("highlight", background="yellow")
    text_box.see(start_idx)

# --- TTS MAIN LOGIC ---
def speak():
    """
    Called when user presses Speak. Spawns a background thread
    to read the entire text, split into sentences, with optional pause/resume.
    """
    global is_playing
    is_paused.clear()
    is_stopped.clear()
    is_playing = True

    def run_tts():
        global is_playing  # Declare is_playing as global here
        text = text_box.get(tk.INSERT, tk.END).strip()
        if not text:
            print("No text to speak.")
            is_playing = False
            return

        # Split into sentences
        import re
        sentences = re.split(r'(?<=[.!?])\s+', text)
        positions = get_sentence_positions(sentences)

        for i, (sentence, (start_idx, end_idx)) in enumerate(zip(sentences, positions)):
            if is_stopped.is_set():
                break
            # Wait while paused
            while is_paused.is_set():
                time.sleep(0.1)

            highlight_sentence(start_idx, end_idx)

            # Generate wav for the sentence
            temp_filename = f"temp_{i}.wav"
            tts.tts_to_file(text=sentence, file_path=temp_filename, speed=speed_factor)

            # Play the generated audio
            data, fs = sf.read(temp_filename, dtype='float32')
            if is_stopped.is_set():
                break
            try:
                sd.play(data, fs)
                sd.wait()
            except Exception as e:
                print("Playback error:", e)
                break
            finally:
                if os.path.exists(temp_filename):
                    os.remove(temp_filename)

        # Remove highlight after reading
        text_box.tag_remove("highlight", "1.0", tk.END)
        is_playing = False

    # Start TTS in background
    threading.Thread(target=run_tts, daemon=True).start()

def pause():
    global is_playing
    print("pause")
    is_paused.set()
    try:
        if is_playing:
            sd.stop()
    except Exception as e:
        print("Audio already stopped:", e)

def resume():
    print("resume")
    is_paused.clear()

def stop():
    global is_playing
    print("stop")
    is_stopped.set()
    try:
        if is_playing:
            sd.stop()
    except Exception as e:
        print("Could not stop audio:", e)
    text_box.tag_remove("highlight", "1.0", tk.END)
    is_playing = False

def update_speed(val):
    global speed_factor
    speed_factor = float(val)
    print("Speed:", speed_factor)

def get_sentence_positions(sentences):
    positions = []
    idx = "1.0"
    for sentence in sentences:
        hit = text_box.search(sentence.strip(), idx, stopindex=tk.END, nocase=True)
        if not hit:
            continue
        start_idx = hit
        end_idx = f"{hit} + {len(sentence)}c"
        positions.append((start_idx, end_idx))
        idx = end_idx
    return positions

# Buttons
speak_button = tk.Button(root, text="Speak", bg="white", font=("Arial", 12), command=speak)
speak_button.place(x=120, y=10)

pause_button = tk.Button(root, text="Pause", bg="white", font=("Arial", 12), command=pause)
pause_button.place(x=180, y=10)

resume_button = tk.Button(root, text="Resume", bg="white", font=("Arial", 12), command=resume)
resume_button.place(x=240, y=10)

stop_button = tk.Button(root, text="Stop", bg="white", font=("Arial", 12), command=stop)
stop_button.place(x=310, y=10)

translate_button = tk.Button(root, text="Translate Selection", bg="white", font=("Arial", 12), command=translate_selection)
translate_button.place(x=10, y=400)

speed_scale = tk.Scale(root, from_=0.5, to=2.0, resolution=0.1, orient=tk.HORIZONTAL, command=update_speed,
                       label="Speed")
speed_scale.set(speed_factor)
speed_scale.place(x=150, y=400)

def on_close():
    stop()
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_close)
root.mainloop()