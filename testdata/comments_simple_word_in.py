"""File docstring to exercise `exercise.myfunc()` in exercise.py.

Some occurrences of 'exercise' should get renamed but some should not.
It depends if it seems like something that exercises "exercise" as a
normal word or one that is using it as a filename.  If it were
content_exercise or exercise_util -- or `exercise` -- it wouldn't be
an issue.
"""
import exercise


_WHITELIST = [
    'exercise',
    'exercise.myfunc',
]

def f():
    f = exercise.myfunc()
    # We exercise exercise.myfunc from exercise.py.
    self.mock_function('exercise.myfunc', lambda: None)
