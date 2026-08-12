"""Configuration loading for the Ohbot demo.

Reads config.yaml, then deep-merges config.local.yaml over it if present, so
machine-specific settings (audio devices, mostly) stay out of git while the
shared defaults are committed.

Precedence, lowest to highest:
    code defaults  <  config.yaml  <  config.local.yaml  <  command-line flags

Missing keys always fall back to the constants defined in each module, so a
partial config -- or no config at all -- still runs.
"""

import os
import sys

import yaml

DEFAULT_PATH = "config.yaml"
LOCAL_PATH = "config.local.yaml"

# Sections we understand. A typo shouldn't kill the demo, but it shouldn't be
# silent either -- an ignored setting looks identical to a setting that did
# nothing.
KNOWN_SECTIONS = {
    "audio",
    "llm",
    "tts",
    "speech_to_text",
    "robot",
    "persona",
    "personas",
}


def _deep_merge(base, override):
    """Recursively merge override into base, returning a new dict."""
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Config:
    """Nested settings with dotted-path lookup."""

    def __init__(self, data=None, sources=()):
        self.data = data or {}
        self.sources = list(sources)

    def get(self, path, default=None):
        """Fetch by dotted path, e.g. get("llm.model").

        Returns default when the path is missing or explicitly null, so a
        `key: null` in YAML means "use the built-in default".
        """
        node = self.data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return default if node is None else node

    def section(self, name):
        value = self.data.get(name)
        return value if isinstance(value, dict) else {}

    def persona(self, name=None):
        """Resolve the active persona to a dict of overrides."""
        name = name or self.get("persona")
        if not name:
            return {}
        personas = self.section("personas")
        if name not in personas:
            raise KeyError(
                "Unknown persona {!r}. Available: {}".format(
                    name, ", ".join(sorted(personas)) or "(none defined)"
                )
            )
        return personas[name] or {}

    def __repr__(self):
        return "Config(sources={})".format(self.sources)


def load(path=DEFAULT_PATH, local_path=LOCAL_PATH, warn=True):
    """Load config.yaml plus any config.local.yaml override."""
    data = {}
    sources = []

    for candidate in (path, local_path):
        if not candidate or not os.path.exists(candidate):
            continue
        try:
            with open(candidate) as f:
                loaded = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise RuntimeError("Could not parse {}: {}".format(candidate, e)) from e

        if not isinstance(loaded, dict):
            raise RuntimeError("{} must contain a mapping at the top level".format(candidate))

        data = _deep_merge(data, loaded)
        sources.append(candidate)

    if warn:
        for key in data:
            if key not in KNOWN_SECTIONS:
                print(
                    "[config] Ignoring unknown section {!r} (known: {})".format(
                        key, ", ".join(sorted(KNOWN_SECTIONS))
                    ),
                    file=sys.stderr,
                )

    return Config(data, sources)


if __name__ == "__main__":
    cfg = load()
    print("sources:", cfg.sources or "(none -- using code defaults)")
    print(yaml.safe_dump(cfg.data, sort_keys=False, default_flow_style=False))
