"""Axolotl plugin: publish full checkpoints after Trainer finishes each save."""

import json
import os
from pathlib import Path

from axolotl.integrations.base import BasePlugin
from transformers import TrainerCallback

from checkpoint_store import publish_checkpoint, write_json


class DurableCheckpointCallback(TrainerCallback):
    def __init__(self):
        self.artifacts = Path(os.environ["ARTIFACT_DIR"])
        self.contract_hash = os.environ["RUN_CONTRACT_HASH"]
        self.session = os.environ["RUN_SESSION"]
        self.stop_after = int(os.environ.get("STOP_AFTER_STEP", "0"))

    def on_train_begin(self, args, state, control, **kwargs):
        event = {"event": "training_started", "session": self.session, "global_step": state.global_step}
        print(json.dumps(event), flush=True)
        write_json(self.artifacts / f"checkpoint-events-{self.session}-start.json", event)

    def on_save(self, args, state, control, **kwargs):
        if not state.is_world_process_zero:
            return control
        checkpoint = Path(args.output_dir) / f"checkpoint-{state.global_step}"
        published = publish_checkpoint(checkpoint, self.artifacts, self.contract_hash)
        event = {"event": "checkpoint_published", "global_step": state.global_step,
                 "directory": published.name, "session": self.session}
        write_json(self.artifacts / f"checkpoint-events-{self.session}-step{state.global_step}.json", event)
        print(json.dumps(event), flush=True)
        if self.stop_after and state.global_step >= self.stop_after:
            # A controlled checkpoint boundary exercises recovery on a fresh Job.
            # It is deliberately not labelled as an actual Spot preemption.
            control.should_training_stop = True
        return control


class SpotCheckpointPlugin(BasePlugin):
    def add_callbacks_post_trainer(self, cfg, trainer):
        return [DurableCheckpointCallback()]
