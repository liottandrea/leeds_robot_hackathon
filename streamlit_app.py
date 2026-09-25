"""Presenter control panel: the Ohbot kids'-content demo, plus a launcher for
every example and the full chat app.

    streamlit run streamlit_app.py

"Kids' Content" -- type a character and a topic, pick a content type, and Ohbot
performs a short rhyme/joke/story with matching facial expressions. "Generate &
Perform" calls Claude on Amazon Bedrock via the AWS CLI profile named in
config.yaml's kids_content.aws_profile (default: genai-agent-user); no API key
needed. "Use fallback instead" works even without AWS credentials configured at
all.

"Examples" / "Full App" -- run any examples/*.py script or ohbot_chat.py as a
real subprocess (exactly as documented on the command line), with its output
streamed into the page. Scripts that read input() get a text box wired to
their stdin; mic/camera-driven ones just use the machine's real hardware.

Settings (audio devices, robot idle behaviour, voices, Bedrock profile/model)
come from config.yaml / config.local.yaml, same as ohbot_chat.py.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import truststore

    truststore.inject_into_ssl()  # trust the OS cert store, for corporate TLS-inspecting proxies
except Exception:
    pass

import anthropic
import sounddevice as sd
import streamlit as st
from streamlit.runtime.scriptrunner import add_script_run_ctx

from ohbot import ohbot
from ohbot_kit import audio, kids_content, llm, tts
from ohbot_kit import config as config_mod
from ohbot_kit.robot import Ohbot

REPO_ROOT = Path(__file__).resolve().parent

CONTENT_TYPES = ("nursery rhyme", "joke", "story")
STATUS_LABELS = {
    "idle": "Idle",
    "generating": "Generating...",
    "speaking": "Speaking...",
    "error": "Error",
}


@dataclass(frozen=True)
class ArgSpec:
    """One CLI argument a script accepts, rendered as a dedicated widget.

    kind:
      "flag"         -- a boolean switch, e.g. --voice. Renders a checkbox.
      "choice"       -- must be one of a fixed set. Renders a dropdown.
      "multi_choice" -- zero or more of a fixed set, passed positionally
                        (no flag). Renders a multiselect.
      "text"         -- free-form value, but with real suggestions from this
                        repo's own config/docs. Renders a dropdown of
                        suggestions plus a "Custom..." option that reveals a
                        text box.
      "number"       -- a numeric value with a script-side default; only
                        passed if changed from that default.

    choices/suggestions can instead be resolved at render time from
    config.yaml via `dynamic` ("personas", "voices", or "ollama_models"), so
    the dropdown stays in sync if personas/models are added or renamed.
    """

    kind: str
    label: str
    flag: str = ""  # "" means positional (no --flag, just the value)
    choices: tuple[str, ...] = ()
    suggestions: tuple[str, ...] = ()
    dynamic: str = ""  # "" | "personas" | "voices" | "ollama_models"
    default: str = "0"  # kind == "number" only
    step: float = 1.0  # kind == "number" only


@dataclass(frozen=True)
class Runnable:
    """One example/app script the hub can launch as a subprocess."""

    key: str
    label: str
    script: str  # path relative to REPO_ROOT
    description: str
    stdin: bool = False  # show a "send to stdin" box while it's running
    args: tuple[ArgSpec, ...] = ()
    advanced_hint: str = ""  # placeholder for the free-form "other args" box
    chat_transcript: bool = False  # show a "last messages" panel above the log


EXAMPLES: tuple[Runnable, ...] = (
    Runnable("ex01", "01 - Hello Robot", "examples/01_hello_robot.py",
              "Move, speak, look around -- start here."),
    Runnable("ex02", "02 - Expressions", "examples/02_expressions.py",
              "The full catalogue of poses and gestures.",
              args=(ArgSpec(kind="choice", label="Category",
                             choices=("poses", "gestures", "looks")),)),
    Runnable("ex03", "03 - Speech", "examples/03_speech.py",
              "54 voices, speed, and how lip sync works.",
              args=(
                  ArgSpec(kind="flag", label="List voices only", flag="--list-voices"),
                  ArgSpec(kind="text", label="Voice", flag="--voice", dynamic="voices"),
              )),
    Runnable("ex04", "04 - Chat (basic)", "examples/04_chat_basic.py",
              "The smallest possible talking robot.", stdin=True),
    Runnable("ex05", "05 - Personas", "examples/05_personas.py",
              "One robot, different characters.",
              args=(ArgSpec(kind="multi_choice", label="Personas to demo (default: all)",
                             dynamic="personas"),)),
    Runnable("ex06", "06 - Voice Chat", "examples/06_voice_chat.py",
              "Talk to it with your real microphone."),
    Runnable("ex07", "07 - Sensors", "examples/07_sensors.py",
              "React to someone approaching -- needs a real sensor, runs forever."),
    Runnable("ex08", "08 - Empathy Chat (flagship)", "examples/08_empathy_chat.py",
              "Reacts with face and body, not just words.",
              stdin=True,
              args=(
                  ArgSpec(kind="flag", label="Voice input", flag="--voice"),
                  ArgSpec(kind="text", label="Model", flag="--model", suggestions=("phi4-mini",)),
              )),
    Runnable("ex09", "09 - Vision", "examples/09_vision.py",
              "Webcam + a vision model describes what it sees.",
              args=(
                  ArgSpec(kind="text", label="Model", flag="--model",
                          suggestions=("moondream", "qwen3.6:35b")),
                  ArgSpec(kind="number", label="Interval (seconds)", flag="--interval", default="8"),
                  ArgSpec(kind="number", label="Camera index", flag="--camera", default="0"),
              )),
    Runnable("ex10", "10 - Teams Call", "examples/10_teams_call.py",
              "Sits in a call, answers when named -- needs audio routing set up first.",
              args=(
                  ArgSpec(kind="flag", label="List audio devices only", flag="--list-devices"),
                  ArgSpec(kind="text", label="Model", flag="--model", suggestions=("phi4-mini",)),
                  ArgSpec(kind="text", label="Input device", flag="--input", suggestions=("BlackHole 2ch",)),
                  ArgSpec(kind="text", label="Output device", flag="--output", suggestions=("BlackHole 16ch",)),
              )),
    Runnable("ex11", "11 - Multi-beat", "examples/11_multi_beat.py",
              "Expression that changes within a single reply.", stdin=True),
)

FULL_APP: tuple[Runnable, ...] = (
    Runnable("ohbot_chat", "ohbot_chat.py", "ohbot_chat.py",
              "The full chat app: persona, voice, and reply mode.",
              stdin=True,
              args=(
                  ArgSpec(kind="choice", label="Persona", flag="--persona", dynamic="personas"),
                  ArgSpec(kind="flag", label="Voice input", flag="--voice"),
                  ArgSpec(kind="flag", label="Camera (let it see you)", flag="--camera"),
                  ArgSpec(kind="choice", label="Mode", flag="--mode",
                          choices=("empathy", "beats", "plain")),
                  ArgSpec(kind="text", label="Model", flag="--model",
                          suggestions=("phi4-mini",), dynamic="ollama_models"),
                  ArgSpec(kind="flag", label="List audio devices only", flag="--list-devices"),
              ),
              advanced_hint="--speed 1.4 | --voice-name af_sky | --max-sentences 3",
              chat_transcript=True),
)


@st.cache_resource
def get_config() -> config_mod.Config:
    return config_mod.load()


@st.cache_resource
def get_llm_client() -> tuple[anthropic.AnthropicBedrock | None, str | None]:
    """Build the Bedrock client once for the app's lifetime.

    Returns (client, error). Unlike get_robot(), a failure here should not
    take down the whole app -- it only disables "Generate & Perform"; "Use
    fallback instead" and "Stop" must keep working regardless.

    timeout/max_retries are set here, at construction, rather than via
    client.with_options(...) at call time -- AnthropicBedrock.with_options()
    (i.e. .copy()) doesn't forward aws_profile, so calling it silently drops
    profile-based auth and falls back to boto3's default credential chain.
    """
    cfg = get_config()
    try:
        client = anthropic.AnthropicBedrock(
            aws_profile=cfg.get("kids_content.aws_profile", "genai-agent-user"),
            aws_region=cfg.get("kids_content.aws_region"),  # None -> auto-detect
            timeout=kids_content.TIMEOUT_SECONDS,
            max_retries=0,
        )
        return client, None
    except Exception as e:
        return None, f"Content generation unavailable: Bedrock setup error ({e})"


@st.cache_resource
def get_robot() -> tuple[Ohbot | None, str | None]:
    """Connect to the robot once for the app's lifetime.

    Returns (bot, error). On failure bot is None and error is a
    "Robot not responding" message -- callers must check for None, since
    Streamlit may call this again if the process restarts.
    """
    cfg = get_config()
    try:
        out_device = audio.resolve(cfg.get("audio.output_device"), audio.OUTPUT)
        # A concrete device (never None) is required so playback goes through
        # sounddevice, which is what makes the Stop button able to cut audio.
        audio.install_output(out_device if out_device is not None else sd.default.device[1])
    except audio.DeviceNotFound as e:
        return None, f"Robot not responding: audio device error ({e})"

    try:
        if not ohbot.connected:
            # ohbot.init() only auto-runs once, at module import. If
            # release_robot() closed the port (or the very first import-time
            # attempt failed while nothing was plugged in yet), it must be
            # called again here or Ohbot().__enter__() below would silently
            # no-op forever against a dead connection.
            ohbot.init()
        bot = Ohbot(
            idle=cfg.get("robot.idle", True),
            colours=cfg.get("robot.eye_colours"),
            blink_interval=cfg.get("robot.blink_interval", (2, 6)),
            drift_interval=cfg.get("robot.drift_interval", (4, 9)),
        )
        bot.__enter__()  # kept open until release_robot() explicitly closes it
        return bot, None
    except Exception as e:
        return None, f"Robot not responding: {e}"


def release_robot() -> None:
    """Close the hub's own serial connection before a subprocess needs the port.

    get_robot() holds the connection open across reruns so Kids' Content
    doesn't reconnect every time (see its docstring). But Examples/Full App
    entries are separate processes that open the same USB-serial device
    themselves -- if the hub still has it open, their own ohbot.init() fails
    to claim the port, that failure is swallowed internally, and every
    pose/gesture call in that process silently becomes a no-op for its whole
    life. Only acts if a connection actually exists, so this is a no-op when
    Kids' Content was never opened this session.
    """
    if not st.session_state.get("robot_connected"):
        return
    bot, _ = get_robot()
    if bot is not None:
        bot.__exit__(None, None, None)
    get_robot.clear()
    st.session_state["robot_connected"] = False


def ensure_voice(cfg: config_mod.Config, content_type: str, persona: dict | None = None) -> None:
    """Install the right voice+speed, only if they changed.

    persona (a config.yaml personas.* entry) overrides the content-type
    mapping when set -- both voice and speed, since some personas (chipmunk,
    bear) only sound right at their own speed.
    """
    if persona:
        voice = persona.get("voice") or tts.DEFAULT_VOICE
        speed = persona.get("speed") or cfg.get("tts.speed", tts.DEFAULT_SPEED)
    else:
        voice = kids_content.voice_for_content_type(cfg, content_type, tts.DEFAULT_VOICE)
        speed = cfg.get("tts.speed", tts.DEFAULT_SPEED)

    if st.session_state.installed_tts_voice == (voice, speed):
        return
    try:
        tts.install(tts.KokoroTTS(voice=voice, speed=speed))
        st.session_state.installed_tts_voice = (voice, speed)
    except Exception as e:
        # A demo with the wrong voice beats a demo that crashes on a missing
        # Kokoro file, so fall back to whatever's already installed.
        print(f"[tts] could not install voice {voice!r}: {e}")


def _worker(
    bot: Ohbot,
    client: anthropic.AnthropicBedrock | None,
    character: str,
    topic: str,
    content_type: str,
    model: str,
    request_id: int,
    stop_event: threading.Event,
    use_fallback: bool,
    persona: dict | None,
) -> None:
    def superseded() -> bool:
        return stop_event.is_set() or st.session_state.get("request_id") != request_id

    if use_fallback:
        content = kids_content.get_fallback(content_type)
    else:
        assert client is not None, "caller must not start a non-fallback request without a client"
        try:
            content = kids_content.generate(
                client, character, topic, content_type, model=model, persona=persona
            )
        except kids_content.GenerationError as e:
            if not superseded():
                st.session_state.error_message = f"Content generation failed: {e}"
                st.session_state.status = "error"
            return

        problems = kids_content.filter_content(content)
        if problems:
            if not superseded():
                st.session_state.error_message = (
                    "Content failed the safety filter (" + "; ".join(problems) + "). "
                    "Use the fallback button instead."
                )
                st.session_state.status = "error"
            return

    if superseded():
        return
    st.session_state.content = content
    st.session_state.status = "speaking"

    try:
        kids_content.perform(bot, content, stop_event)
    except Exception as e:
        if not superseded():
            st.session_state.error_message = f"Robot not responding: {e}"
            st.session_state.status = "error"
        return

    if not superseded():
        st.session_state.status = "idle"


def start_request(bot, client, character, topic, content_type, model, use_fallback, persona=None) -> None:
    st.session_state.request_id += 1
    my_request_id = st.session_state.request_id
    stop_event = threading.Event()
    st.session_state.stop_event = stop_event
    st.session_state.error_message = None
    st.session_state.content = None
    st.session_state.status = "generating" if not use_fallback else "speaking"

    ensure_voice(get_config(), content_type, persona)

    thread = threading.Thread(
        target=_worker,
        args=(
            bot, client, character, topic, content_type, model,
            my_request_id, stop_event, use_fallback, persona,
        ),
        daemon=True,
    )
    add_script_run_ctx(thread)  # lets the thread write st.session_state safely
    st.session_state.worker_thread = thread
    thread.start()


def handle_stop(bot) -> None:
    st.session_state.stop_event.set()
    sd.stop()
    if bot is not None:
        bot.express("neutral")
    st.session_state.request_id += 1
    st.session_state.status = "idle"
    st.session_state.error_message = None


def init_session_state() -> None:
    defaults = {
        "status": "idle",
        "content": None,
        "error_message": None,
        "stop_event": threading.Event(),
        "worker_thread": None,
        "request_id": 0,
        "installed_tts_voice": None,
        "runner_proc": None,
        "runner_output": "",
        "runner_key": None,
        "audio_output_choice": get_config().get("audio.output_device"),
        "audio_input_choice": get_config().get("audio.input_device"),
        "robot_connected": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_kids_content() -> None:
    bot, robot_error = get_robot()
    client, llm_error = get_llm_client()
    cfg = get_config()
    model = cfg.get("kids_content.model", kids_content.DEFAULT_MODEL)

    status_box = st.empty()
    status_box.markdown(f"**Status:** {STATUS_LABELS.get(st.session_state.status, st.session_state.status)}")

    if robot_error:
        st.error(robot_error)
        if st.button("Retry connecting to the robot"):
            get_config.clear()
            get_robot.clear()
            st.rerun()
        st.stop()

    st.session_state["robot_connected"] = True

    if llm_error:
        st.warning(f"{llm_error} -- \"Generate & Perform\" is disabled; \"Use fallback instead\" still works.")

    if st.session_state.status == "error" and st.session_state.error_message:
        st.error(st.session_state.error_message)

    character = st.text_input("Character", placeholder="e.g. a brave little fox")
    topic = st.text_input("Topic", placeholder="e.g. going to the moon")
    content_type = st.radio("Content type", CONTENT_TYPES, horizontal=True)

    persona_names = sorted(cfg.section("personas"))
    persona_choice = st.selectbox("Persona", ["Auto (match content type)"] + persona_names)
    persona = None if persona_choice.startswith("Auto") else cfg.persona(persona_choice)

    busy = st.session_state.status in ("generating", "speaking")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Generate & Perform", disabled=busy or client is None, type="primary"):
            start_request(bot, client, character, topic, content_type, model, use_fallback=False, persona=persona)
            st.rerun()
    with col2:
        if st.button("Use fallback instead"):
            start_request(bot, client, character, topic, content_type, model, use_fallback=True, persona=persona)
            st.rerun()
    with col3:
        if st.button("Stop", disabled=not busy):
            handle_stop(bot)
            st.rerun()

    if st.session_state.content:
        segments = st.session_state.content["segments"]
        text = "\n".join(
            f"[{seg['expression']}{' + pause' if seg.get('pause_before') else ''}] {seg['text']}"
            for seg in segments
        )
        st.text_area("Performance", value=text, height=200, disabled=True)

    if busy:
        time.sleep(0.4)
        st.rerun()


def _pump_output(proc: subprocess.Popen) -> None:
    """Stream a subprocess's merged stdout/stderr into proc's own buffer, line by line.

    Runs on a background thread since proc.stdout.readline() blocks. Deliberately
    does NOT touch st.session_state: this thread lives for the whole subprocess,
    but the Run panel's own polling (`render_runner`'s `time.sleep(0.4); st.rerun()`
    while a script is active) starts a new script run every ~0.4s. A background
    thread registered to one run via add_script_run_ctx gets StopException the
    next time it touches session state once that run is superseded -- with
    unbuffered output arriving line by line, that happens almost immediately, so
    the thread would die a line or two in and the log would appear to freeze.
    Writing to a plain lock-protected list on `proc` instead sidesteps that
    entirely; render_runner (running safely in the current script run) reads it.
    """
    assert proc.stdout is not None, "caller must construct proc with stdout=PIPE"
    for line in iter(proc.stdout.readline, ""):
        with proc.output_lock:
            proc.output_lines.append(line)
    proc.stdout.close()


def start_runnable(entry: Runnable, argv: list[str]) -> None:
    release_robot()
    st.session_state.runner_key = entry.key
    st.session_state.runner_output = ""
    proc = subprocess.Popen(
        [sys.executable, entry.script, *argv],
        cwd=REPO_ROOT,
        stdin=subprocess.PIPE if entry.stdin else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    proc.output_lock = threading.Lock()
    proc.output_lines = []
    st.session_state.runner_proc = proc
    thread = threading.Thread(target=_pump_output, args=(proc,), daemon=True)
    thread.start()


def _snapshot_output(proc: subprocess.Popen) -> str:
    """Safe to call from the main script run: copies proc's buffer into a string."""
    with proc.output_lock:
        return "".join(proc.output_lines)


def stop_runnable() -> None:
    proc = st.session_state.runner_proc
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
    if proc is not None:
        st.session_state.runner_output = _snapshot_output(proc)
    st.session_state.runner_proc = None


def send_line(text: str) -> None:
    proc = st.session_state.runner_proc
    if proc is not None and proc.stdin is not None and proc.poll() is None:
        proc.stdin.write(text + "\n")
        proc.stdin.flush()


def _resolve_choices(spec: ArgSpec, cfg: config_mod.Config) -> tuple[str, ...]:
    """Pull persona names / voice suggestions live from config.yaml, not a hardcoded copy."""
    if spec.dynamic == "personas":
        return tuple(sorted(cfg.section("personas")))
    if spec.dynamic == "voices":
        voices = {p.get("voice") for p in cfg.section("personas").values() if p.get("voice")}
        return tuple(sorted(voices))
    if spec.dynamic == "ollama_models":
        try:
            models = llm.list_models(cfg.get("llm.host", llm.HOST))
        except llm.OllamaError:
            models = list(spec.suggestions)
        return tuple(models) + (llm.BEDROCK_MODEL_ALIAS,)
    return spec.choices


def render_args(entry: Runnable, cfg: config_mod.Config, disabled: bool) -> list[str]:
    """Render one widget per ArgSpec, plus a free-text fallback, and build argv."""
    argv: list[str] = []
    positional: list[str] = []

    for spec in entry.args:
        widget_key = f"arg_{entry.key}_{spec.flag or spec.label}"

        if spec.kind == "flag":
            if st.checkbox(spec.label, disabled=disabled, key=widget_key):
                argv.append(spec.flag)

        elif spec.kind == "choice":
            choices = _resolve_choices(spec, cfg)
            value = st.selectbox(spec.label, ["(default)", *choices], disabled=disabled, key=widget_key)
            if value != "(default)":
                if spec.flag:
                    argv.extend([spec.flag, value])
                else:
                    positional.append(value)

        elif spec.kind == "multi_choice":
            choices = _resolve_choices(spec, cfg)
            values = st.multiselect(spec.label, choices, disabled=disabled, key=widget_key)
            positional.extend(values)

        elif spec.kind == "text":
            suggestions = _resolve_choices(spec, cfg) or spec.suggestions
            options = ["(default)", *suggestions, "Custom..."]
            picked = st.selectbox(spec.label, options, disabled=disabled, key=f"{widget_key}_select")
            value = picked
            if picked == "Custom...":
                value = st.text_input(f"{spec.label} (custom)", disabled=disabled, key=f"{widget_key}_custom")
            if value and value not in ("(default)", "Custom..."):
                if spec.flag:
                    argv.extend([spec.flag, value])
                else:
                    positional.append(value)

        elif spec.kind == "number":
            value = st.number_input(
                spec.label, value=float(spec.default), step=spec.step, disabled=disabled, key=widget_key
            )
            if value != float(spec.default):
                argv.extend([spec.flag, str(value)])

    return [*argv, *positional]


_TURN_RE = re.compile(r"^(You|Ohbot(?:\s*\[[^\]]+\])?): (.*)$")


def _parse_chat_turns(output: str) -> list[tuple[str, str]]:
    """Pull (role, text) turns out of ohbot_chat.py's own log lines."""
    turns = []
    for line in output.splitlines():
        m = _TURN_RE.match(line)
        if m:
            role = "user" if m.group(1) == "You" else "assistant"
            turns.append((role, m.group(2)))
    return turns


def render_runner(entry: Runnable) -> None:
    """Run/stop panel shared by every entry in EXAMPLES and FULL_APP.

    A plain subprocess, not a rewrite of the script -- so the script behaves
    exactly as it does from a terminal, including talking to real mic/camera
    hardware directly rather than through the browser.
    """
    st.subheader(entry.label)
    st.caption(entry.description)

    proc = st.session_state.runner_proc
    is_current = proc is not None and st.session_state.runner_key == entry.key
    running = is_current and proc.poll() is None
    if is_current:
        # Safe here (main script run) even though _pump_output fills proc's
        # buffer from a background thread -- see _pump_output's docstring.
        st.session_state.runner_output = _snapshot_output(proc)

    argv = render_args(entry, get_config(), disabled=running)
    advanced = st.text_input(
        "Other args (advanced)", placeholder=entry.advanced_hint, disabled=running, key=f"args_{entry.key}"
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Run", disabled=running, type="primary", key=f"run_{entry.key}"):
            start_runnable(entry, [*argv, *shlex.split(advanced)])
            st.rerun()
    with col2:
        if st.button("Stop", disabled=not running, key=f"stop_{entry.key}"):
            stop_runnable()
            st.rerun()

    if entry.stdin and running:
        line = st.text_input("Send to script (stdin)", key=f"stdin_{entry.key}")
        if st.button("Send", key=f"send_{entry.key}") and line:
            send_line(line)

    if "--camera" in argv and running:
        if st.button("Take a picture", key=f"photo_{entry.key}"):
            send_line("/look")

    if entry.chat_transcript:
        st.caption("Last messages")
        with st.container(height=220, border=True):
            for role, text in _parse_chat_turns(st.session_state.runner_output)[-5:]:
                st.chat_message(role).write(text)

    st.text_area(
        "Output",
        value=st.session_state.runner_output[-4000:],
        height=320,
        disabled=True,
        key=f"out_{entry.key}",
    )

    if proc is not None and st.session_state.runner_key == entry.key and not running:
        st.caption(f"Exited with code {proc.returncode}")

    if running:
        time.sleep(0.4)
        st.rerun()


def _device_options(kind: str) -> list[tuple[str, str | None]]:
    """[(label, name-or-None)] for a selectbox; None means "system default"."""
    return [("System default", None)] + [(info["name"], info["name"]) for _, info in audio.devices(kind)]


def render_audio_sidebar() -> None:
    """Sidebar control to switch audio devices without editing config.local.yaml.

    Persists to config.local.yaml (picked up by every script via the usual
    config precedence) and, for output only, applies live via
    audio.install_output() -- input has no live-swap mechanism and Kids'
    Content never opens a microphone in-process anyway.

    Deliberately never touches get_robot()'s cache: a working robot keeps
    speaking through the live install_output() call alone, and recovering a
    broken one is a separate, explicit action (the "Retry" button in
    render_kids_content()) so a routine device switch can't accidentally
    trigger a duplicate Ohbot().__enter__().
    """
    with st.sidebar.expander("🔊 Audio devices"):
        for kind, cfg_key, session_key, widget_label in (
            (audio.OUTPUT, "audio.output_device", "audio_output_choice", "Output device"),
            (audio.INPUT, "audio.input_device", "audio_input_choice", "Input device"),
        ):
            try:
                options = _device_options(kind)
            except Exception as e:
                st.caption(f"Device list unavailable: {e}")
                continue

            current = st.session_state[session_key]
            labels = [label for label, _ in options] + ["Custom..."]
            try:
                index = next(i for i, (_, name) in enumerate(options) if name == current)
            except StopIteration:
                index = len(labels) - 1  # a configured name not currently plugged in

            picked = st.selectbox(widget_label, labels, index=index, key=f"select_{session_key}")
            if picked == "Custom...":
                new_value = st.text_input(
                    f"{widget_label} name (substring)", value=current or "", key=f"custom_{session_key}"
                ) or None
            else:
                new_value = next(name for label, name in options if label == picked)

            if new_value != current:
                section, field = cfg_key.split(".")
                config_mod.update_local({section: {field: new_value}})
                st.session_state[session_key] = new_value
                get_config.clear()
                if kind == audio.OUTPUT:
                    try:
                        idx = audio.resolve(new_value, audio.OUTPUT)
                        audio.install_output(idx if idx is not None else sd.default.device[1])
                    except audio.DeviceNotFound:
                        pass  # not connected right now; takes effect once it is
                st.rerun()

            try:
                audio.resolve(new_value, kind)
            except audio.DeviceNotFound:
                st.caption("⚠️ Not currently connected -- will apply once it is.")


def main() -> None:
    st.set_page_config(page_title="Ohbot Demo Hub", page_icon="🤖")
    init_session_state()

    st.title("🤖 Ohbot Demo Hub")

    st.sidebar.title("Demo")
    category = st.sidebar.radio("Category", ["Kids' Content", "Examples", "Full App"])
    render_audio_sidebar()

    if category == "Kids' Content":
        render_kids_content()
        return

    registry = EXAMPLES if category == "Examples" else FULL_APP
    choice = st.sidebar.selectbox("Script", [e.label for e in registry])
    render_runner(next(e for e in registry if e.label == choice))


if __name__ == "__main__":
    main()
