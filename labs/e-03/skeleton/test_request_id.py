"""Completion tier, step one: the test is worth more than the function.

    cd labs/e-03/skeleton && python3 -m pytest -q test_request_id.py

Write the assertions before you write `request_id_for`. Two calls with the same run and step
give the same key. Nothing about the clock, a random source or the model's output can change it.
A different step in the same run gives a different key, or two writes in one run would collide.
"""

from activities import request_id_for  # noqa: F401


def test_same_run_and_step_give_the_same_key():
    raise NotImplementedError("write me first")


def test_the_clock_does_not_change_the_key():
    raise NotImplementedError("write me: call it twice with time between the calls")


def test_two_steps_of_one_run_do_not_collide():
    raise NotImplementedError("write me")
