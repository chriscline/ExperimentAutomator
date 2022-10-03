import traceback
import sys

# from https://stackoverflow.com/questions/6760685/creating-a-singleton-in-python
class Singleton(type):
    _instances = {}
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]

def exceptionToStr(e: Exception) -> str:

    # from https://stackoverflow.com/a/49613561
    ex_type, ex_value, ex_traceback = sys.exc_info()

    # Extract unformatter stack traces as tuples
    trace_back = traceback.extract_tb(ex_traceback)

    # Format stacktrace
    stack_trace = ''

    eStr = ''

    for trace in trace_back:
        stack_trace += "File : %s , Line : %d, Func.Name : %s, Message : %s\n" % (trace[0], trace[1], trace[2], trace[3])

    eStr += "Exception type : %s\n" % ex_type.__name__
    eStr += "Exception message : %s\n" % ex_value
    eStr += "Stack trace : %s\n" % stack_trace

    return eStr
