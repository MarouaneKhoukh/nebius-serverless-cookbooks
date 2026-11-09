# Contributing

Each cookbook should work from its README, starting with a fresh checkout and a Nebius account. Keep the setup, sample input, run command, expected result and cleanup instructions together.

## Make a change

- Keep examples small enough to run and inspect. Include sample data with its source or license.
- Use placeholders for project IDs and credentials. Keep local results and resource state out of commits.
- Explain where the workload runs, where outputs are saved and what happens after an interruption.
- Use the official Nebius artwork already included in the repository. Keep model and dataset license requirements visible.
- Update the README and configuration together. Verify commands against the supported CLI version.

## Run local checks

For the classification, evaluation, training, video and embedding recipes, run this from the cookbook directory:

```bash
python3 -m unittest discover -s tests -v
```

These local checks use the Python standard library. For the photo search Python application, install `requirements-dev.txt` in its virtual environment and run `python3 -m pytest -q` from `photo-video-ai-search/`.

From the repository root, run the hosted photo demo's separate test suite:

```bash
cd photo-video-ai-search/hosted-demo
npm test
```

Local tests do not provision cloud resources. Cloud testing requires a configured Nebius account and incurs charges. Use a small input, save the result, and stop or cancel the resources you created.

## Open a pull request

Describe the reader-visible change and the checks you ran. Include a small result sample or screenshot when it helps. Put cloud test settings and limitations in the cookbook's validation notes; distinguish an actual interruption from a planned recovery test.
