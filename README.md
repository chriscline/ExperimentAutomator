# ExperimentAutomator

<img alt="Screenshot" src="https://user-images.githubusercontent.com/24940426/235484264-a6f5fe5c-f4ac-4dde-b3c2-3ff88ef8b76c.PNG">

## Install

### Setting up a new experiment protocol

1. Create a new folder for experiment protocol, e.g. `MyExperimentProtocol`.
2. Clone ExperimentAutomator repo as a subfolder in your experiment protocol folder.
    1. [Recommended] If tracking `MyExperimentProtocol` as its own Git repo, you can add ExperimentAutomator as a submodule with `git submodule add https://github.com/chriscline/ExperimentAutomator`
    2. Otherwise, you can clone directly with something like `git clone https://github.com/chriscline/ExperimentAutomator`
    
    Whether you choose the first or second option, the code should be located at `MyExperimentProtocol/ExperimentAutomator`.
3. Install Python 3.10 or greater, and make sure you're calling the correct version of Python when you run `python` commands below.
4. [Recommended] Make a virtualenv for your experiment protocol with something like `python -m venv C:\envs\MyExperimentVenv`. 
    Prior to any commands below, make sure to activate your virtualenv with something like `C:\envs\MyExperimentVenv\Scripts\activate.bat`
5. Install ExperimentAutomator and its dependencies with `pip install -e MyExperimentProtocol/ExperimentAutomator`
6. Create an experiment script as a `.csv` file (e.g. at `MyExperimentProtocol/Scripts/MyExperimentScript.csv`). See [MinimalExample.csv](examples/MinimalExample.csv) for an example.
7. Create an experiment launcher script (e.g. at `MyExperimentProtocol/RunMyExperiment.bat`). A script to activate the virtualenv and launch ExperimentAutomator with your experiment file would be something like:

        @echo off
        setlocal
        CALL C:\envs\MyExperimentVenv\Scripts\activate.bat
        experiment-automator --experimentTable ".\Scripts\MyExperimentScript.csv"
        CALL C:\envs\MyExperimentVenv\Scripts\deactivate.bat
        endlocal
8. Try running the launcher script!

## Development

Dependencies and packaging are managed with [uv](https://docs.astral.sh/uv/). After cloning the repo and [installing uv](https://docs.astral.sh/uv/getting-started/installation/):

- `uv sync` creates a virtual environment at `.venv` and installs dependencies plus ExperimentAutomator itself (as an editable install), downloading a compatible version of Python first if needed.
- `uv run experiment-automator --experimentTable examples\MinimalExample.csv` launches the GUI.
- `uv add <package>` / `uv remove <package>` add or remove dependencies, updating both `pyproject.toml` and `uv.lock`.
- `uv build` builds a source distribution and wheel into `dist/`.
