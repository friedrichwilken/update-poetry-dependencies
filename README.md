This GitHub Action is inspired by the [gha-poetry-update](https://github.com/fuzzylabs/gha-poetry-update) but heavily modified. Similarly, it is a GitHub Action that updates your dependencies based on your `pyproject.toml` file.
The main features it add over the original are:

1. Each package that gets updated is added to a separate commit.
2. You can define a custom command to test the commit. Only successfully tested commits will be pushed.
3. You can define labels that will be added to the resulting pull request.
