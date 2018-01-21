from flask import redirect, render_template, request, session
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


def validate(string):
    regex = "^[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}$"

    return re.match(regex,string)

def days(value):
    if value > 1:
        return str(value) + " days"
    else:
        return str(value) + " day"
