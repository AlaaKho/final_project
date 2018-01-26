from flask import redirect, session
from functools import wraps
import re


def login_required(f):
    """ decorates routes to require login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function

# to validate emails on the server side


def validate(string):
    # https://www.regular-expressions.info/email.html
    regex = "^[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}$"

    return re.match(regex, string)

# filter to view the correct days syntax


def days(value):
    if value > 1:
        return str(value) + " days"
    else:
        return str(value) + " day"
