"""Exercise real request-building code with a fake Ollama client; no downloads."""
import ast
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PersonaChecks(unittest.TestCase):
    def request(self, prompt, history):
        calls = []

        class Client:
            def __init__(self, host):
                self.host = host

            def chat(self, **kwargs):
                calls.append(copy.deepcopy(kwargs))
                return {"message": {"content": "Hello from Nova."}}

        source = ROOT / "eve_main/llm.py"
        nodes = [n for n in ast.parse(source.read_bytes()).body
                 if isinstance(n, ast.FunctionDef)]
        namespace = dict(
            os=os, json=json, ollama=SimpleNamespace(Client=Client),
            BASE_SYSTEM_PROMPT=prompt, MODEL_NAME="nova", ROBOT_NAME="Nova",
            print=lambda *args: None,
        )
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
        reply = namespace["get_ollama_response"]("Hello", history)
        self.assertEqual(reply, "Hello from Nova.")
        self.assertEqual(history[-1], {"role": "assistant", "content": reply})
        return calls[0]

    def test_modelfile_persona_and_options_are_not_overridden(self):
        call = self.request(None, [])
        self.assertEqual(call["model"], "nova")
        self.assertEqual(call["messages"], [{"role": "user", "content": "Hello"}])
        self.assertNotIn("options", call)

    def test_saved_persona_removed_without_losing_conversation(self):
        previous = [{"role": "user", "content": "My name is Sam."},
                    {"role": "assistant", "content": "Hello Sam."}]
        history = [{"role": "system", "content": "Old Eve persona"}, *previous]
        call = self.request(None, history)
        self.assertEqual(call["messages"][:-1], previous)

    def test_explicit_override_replaces_old_system_message(self):
        call = self.request("You are Nova.", [
            {"role": "system", "content": "Old Eve persona"},
            {"role": "user", "content": "Remember me."},
        ])
        systems = [m for m in call["messages"] if m["role"] == "system"]
        self.assertEqual(systems, [{"role": "system", "content": "You are Nova."}])
        self.assertEqual(call["messages"][1]["content"], "Remember me.")


if __name__ == "__main__":
    unittest.main()
