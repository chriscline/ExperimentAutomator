# ExperimentAutomator

## Install

### Setting up a new experiment protocol

1. Create a new folder for experiment protocol, e.g. `MyExperimentProtocol`.
2. Clone ExperimentAutomator repo as a subfolder in your experiment protocol folder.
    1. [Recommended] If tracking `MyExperimentProtocol` as its own Git repo, you can add ExperimentAutomator as a submodule with `git submodule add https://github.com/chriscline/ExperimentAutomator`
    2. Otherwise, you can clone directly with something like `git clone https://github.com/chriscline/ExperimentAutomator`
    
    Whether you choose the first or second option, the code should be located at `MyExperimentProtocol/ExperimentAutomator`.
3. Install Python 3.7 or greater, and make sure you're calling the correct version of Python when you run `python` commands below.
4. [Recommended] Make a virtualenv for your experiment protocol with something like `python -m venv C:\envs\MyExperimentVenv`. 
    Prior to any commands below, make sure to activate your virtualenv with something like `C:\envs\MyExperimentVenv\Scripts\activate.bat`
5. Install Python dependencies for ExperimentAutomator with `pip install -r MyExperimentProtocol/ExperimentAutomator/requirements.txt`
6. Create an experiment script as a `.csv` file (e.g. at `MyExperimentProtocol/Scripts/MyExperimentScript.csv`). See [MinimalExample.csv](examples/MinimalExample.csv) for an example.
7. Create an experiment launcher script (e.g. at `MyExperimentProtocol/RunMyExperiment.bat`). A script to activate the virtualenv and launch ExperimentAutomator with your experiment file would be something like:

        @echo off
        setlocal
        CALL C:\envs\MyExperimentVenv\Scripts\activate.bat
        set PYTHONPATH=%~dp0\ExperimentAutomator
        python %~dp0\ExperimentAutomator\ExperimentAutomatorGUI.py --experimentTable ".\Scripts\MyExperimentScript.csv"
        CALL C:\envs\MyExperimentVenv\Scripts\deactivate.bat
        endlocal
8. Try running the launcher script!
