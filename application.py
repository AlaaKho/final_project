from cs50 import SQL
from flask import Flask, jsonify, flash, redirect, render_template, request, session, url_for, abort
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions
from werkzeug.security import check_password_hash, generate_password_hash
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature, BadSignature

from flask_mail import Mail, Message
from helpers import login_required, validate, days
import os
import datetime
import threading
import time
import sched
import psycopg2

#configure my flask application
app = Flask(__name__)
app.config["JSONIFY_PRETTYPRINT_REGULAR"] = False

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"

#setup your SECRET_KEY
app.config["SECRET_KEY"] = os.urandom(24)
#mail server setup
app.config["MAIL_SERVER"] = 'smtp.googlemail.com'
app.config["MAIL_PORT"]  = 587
app.config["MAIL_USERNAME"] = os.environ.get('MAIL_USERNAME')
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_PASSWORD"] = os.environ.get('MAIL_PASSWORD')

#days filter
app.jinja_env.filters["days"] = days


#add a server side session
Session(app)
#flask mail instance
mail= Mail(app)

#use sqlite and open up the intended database
db = SQL(os.environ.get("DATABASE_URL"))
#declare a token seralizer
ts = URLSafeTimedSerializer(app.config["SECRET_KEY"])


def overdue():

    #date object representing today.
    today = datetime.date.today()
    #get approved requests that should take action today. stringfying today object
    delivery_dates = db.execute("SELECT book_id, user_id, delivery_date FROM requests WHERE delivery_date=:today AND request_type='borrow' ",
     today=str(today))

    #iterate all of the requests that should be inserted into borrowed table today.
    for i in range(len(delivery_dates)):
        copies = db.execute("SELECT * FROM borrowed WHERE user_id=:user_id AND operation=1 AND book_id=:book_id AND transacted=:today",
            user_id=delivery_dates[i]["user_id"], book_id=delivery_dates[i]["book_id"], today=delivery_dates[i]['delivery_date'])

        # ensure borrow operation only inserted once for each item on the delivery date.
        if len(copies) == 0:
            db.execute("INSERT INTO borrowed (user_id, operation, book_id, transacted) VALUES (:user_id, :operation, :book_id, :transacted)",
            user_id=delivery_dates[i]["user_id"], operation=1, book_id=delivery_dates[i]["book_id"], transacted=delivery_dates[i]['delivery_date'])

             #change the book state to on loan
            db.execute("UPDATE books SET state=:state WHERE id=:id", state="on loan",id=delivery_dates[i]["book_id"])


            send_email( delivery_dates[i]["user_id"], delivery_dates[i]["book_id"], operation="borrowed")


    #overdue-
    #get books that are still on loan.
    stl_borrowed = db.execute("SELECT borrowed.user_id, borrowed.book_id, books.lendfor, books.state, borrowed.transacted FROM borrowed JOIN books ON borrowed.book_id=books.id \
      GROUP BY borrowed.book_id HAVING SUM(borrowed.operation) > 0")

    for i in range(len(stl_borrowed)):
        expiry_date = datetime.datetime.strptime(stl_borrowed[i]["transacted"],"%Y-%m-%d") + datetime.timedelta(days =  (stl_borrowed[i]["lendfor"]))

        if datetime.datetime.strptime(str(today),"%Y-%m-%d") >= expiry_date and stl_borrowed[i]["state"] != "overdue":
            db.execute("UPDATE books SET state=:state WHERE id=:id", state="overdue", id=stl_borrowed[i]["book_id"])
            #send email of the overdue item
            send_email( stl_borrowed[i]["user_id"], stl_borrowed[i]["book_id"], operation="overdue")


def schedule_overdue(scheduler=None):
    #https://stackoverflow.com/questions/1404580/
    #create scheduler
    if scheduler is None:
        scheduler = sched.scheduler(time.time, time.sleep)
        #overdue function is called immediately when my server starts
        scheduler.enter(0,1,schedule_overdue, ([scheduler]))
        scheduler.run()

    #repeat everyday
    scheduler.enter(87000, 1, schedule_overdue, ([scheduler]))
    overdue()
    return

t1 = threading.Thread(target=schedule_overdue)
t1.setDaemon(True)
t1.start()


def send_onthread(app, msg, user_email, book_details,  operation):
    # inspired Miguel Grinberg on flask email support
    with app.app_context():
        body =  render_template("email_body.html",username=user_email[0]["username"],title=book_details[0]["title"],
        subtitle=book_details[0]["subtitle"] , authors = book_details[0]["authors"], operation=operation)

        msg.html =  body
        mail.send(msg)


def send_email(user_id, book_id,operation):

    #retrieve user and book details
    book_details = db.execute("SELECT title, subtitle, authors FROM books WHERE id=:id", id=book_id )
    user_email = db.execute("SELECT * FROM users WHERE id=:id", id=user_id)

    if operation == 'overdue':
        subject = "Book you have borrowed is now overdue"
    else:
        subject = "you have " + operation + " a book via Book Stall"

    msg = Message(subject,sender=app.config["MAIL_USERNAME"],recipients=[user_email[0]["email"]])

    t2 = threading.Thread(target=send_onthread, args=[app, msg, user_email, book_details, operation])
    t2.setDaemon(True)
    t2.start()



@app.route("/", methods=["GET", "POST"])
@login_required
def index():

    #ensure api key is provided
    if not os.environ.get("API_KEY"):
        abort(500)

    #check add book form was submitted correctly
    if request.method == "POST":

        if not request.form.get("book"):
            flash(" Must specify Book title")
            return redirect("/")
        if not request.form.get("lendfor"):
            flash(" Must specify lending period")
            return redirect("/")

        #get the form data.
        book = request.form.get("book").split(" ,  ")
        title = book[0].strip()
        subtitle = book[1].strip()
        authors = book[2].strip()
        publisheddate = book[3].strip()

        lendfor = request.form.get("lendfor")
        review = request.form.get("review")
        notes = request.form.get("booknotes")

        #checking if the current user have the selected book already
        brows = db.execute("SELECT * FROM books WHERE title=:title AND subtitle=:subtitle", title=title, subtitle=subtitle)

        #if the book exists in the books table in this user or with other users.
        if len(brows) >= 1:
            #then we check for users table from 0 to the length of brows - 1
            for i in range(len(brows)):
                #for each matching book_id do the following
                book_id =  brows[i]["id"]
                rows = db.execute("SELECT * FROM mycollection WHERE book_id=:book_id AND user_id=:user_id",book_id=book_id, user_id=session["user_id"])
                #IF book existent in the current user's collection
                if len(rows) == 1:
                     flash(" This Book exists in your collection, Edit Book details instead.")
                     return redirect("/")

        #else if the book was never in the books table or not this user's -update books table and mycollection table
        book_id = db.execute("INSERT INTO books (title, subtitle, authors, publisheddate, lendfor, review, notes) VALUES \
         (:title, :subtitle, :authors, :publisheddate, :lendfor, :review, :notes)",title=title,subtitle=subtitle,
          authors=authors, publisheddate=publisheddate, lendfor=lendfor, review=review, notes=notes)

      #update the user mycollection table with the book ID
        db.execute("INSERT INTO mycollection (user_id, book_id) VALUES (:user_id, :book_id)", user_id=session["user_id"], book_id=book_id)
        return redirect("/")

    #on a GET request
    else:

        #owned collection
        mycollection = db.execute("SELECT id, title, subtitle, authors, publishedDate as 'Publish date', lendfor as 'loan period', review, notes,\
         state, time as 'Time added' FROM mycollection INNER JOIN books ON mycollection.book_id = books.id WHERE user_id=:user_id", user_id=session["user_id"])

        #borrowed collection
        borrowed_collection = db.execute("SELECT id, title, subtitle, authors, publishedDate as 'Publish date', lendfor as 'loan period', review, notes,\
          state, transacted as 'Borrowed on' FROM borrowed INNER JOIN books ON borrowed.book_id = books.id WHERE user_id=:user_id GROUP BY borrowed.book_id \
          HAVING SUM(operation) > 0", user_id=session["user_id"])

        return render_template("index.html", mycollection=mycollection, borrowed_collection=borrowed_collection,key=os.environ.get("API_KEY"))



@app.route("/delete", methods=["POST"])
@login_required
def delete():

    if not request.form.get("book_id"):
        flash(" Must Select a book to delete. ")
        return redirect("/")
    #delete book from all records and then go back to the view of home page.
    db.execute("DELETE FROM books WHERE id=:id", id=request.form.get("book_id"))
    db.execute("DELETE FROM mycollection WHERE book_id=:book_id", book_id=request.form.get("book_id"))

    return redirect("/")

@app.route("/edit", methods=["POST"])
@login_required
def edit():

    if not request.form.get("book_id"):
        flash(" Must Select a book to edit. ")
        return redirect("/")

    book_id = request.form.get("book_id")


    #update lending period
    if  request.form.get("lendfor_edit") != "":
        nloan_period = request.form.get("lendfor_edit")
        db.execute("UPDATE books SET lendfor=:lendfor WHERE id=:id", lendfor=nloan_period, id=book_id)

    #update notes
    if  request.form.get("booknotes_edit") != "":
        nbooknotes = request.form.get("booknotes_edit")
        db.execute("UPDATE books SET notes=:notes WHERE id=:id", notes=nbooknotes, id=book_id)

    #update review
    if request.form.get("review_edit") !="":
        nreview = request.form.get("review_edit")
        db.execute("UPDATE books SET review=:review WHERE id=:id", review=nreview, id=book_id)



    return redirect("/")


@app.route("/Return", methods=["POST"])
@login_required
def Return():

    #check if book is selected.
    if not request.form.get("book_id"):
        flash("Must select a book to return!")
        return redirect("/")

    #return_date must be submitted
    if not request.form.get("return_date"):
        flash("Must specify a return date!")
        return redirect("/")

    book_id = request.form.get("book_id")
    #check the database for duplicates of return requests

    rows = db.execute("SELECT * FROM requests WHERE book_id=:book_id AND request_type='Return' AND state='pending'",book_id=book_id)
    if len(rows)!= 0:
        flash("you Have already sent a return request for this book!")
        return redirect("/")

    #else
    owner_id = db.execute("SELECT user_id FROM mycollection WHERE book_id=:book_id",book_id=book_id)
    owner_id = owner_id[0]["user_id"]
    return_date = datetime.timedelta(days=int(request.form.get("return_date"))) + datetime.date.today()



    #insert into requests table
    db.execute("INSERT INTO requests (book_id, owner_id, user_id, request_type, delivery_date) VALUES (:book_id, :owner_id, :user_id, :request_type \
    ,:delivery_date)", book_id=book_id, owner_id=owner_id, user_id=session["user_id"], request_type="Return", delivery_date=return_date)


    return redirect("/")


@app.route("/borrow", methods=["GET","POST"])
@login_required
def borrow():
    if request.method == "POST":
        #get the book id, user requesting id
        if not request.form.get("book_id"):
            flash("Must Select a Book to borrow")
            return redirect ("/borrow")


        book_id = request.form.get("book_id")
        request_user = session["user_id"]

        #initiate a request.
        #retrieve book owner data
        owner_id = db.execute("SELECT user_id FROM mycollection WHERE book_id=:book_id",book_id=book_id)
        owner_id = owner_id[0]["user_id"]

        #insert into requests table
        db.execute("INSERT INTO requests (book_id, owner_id, user_id, request_type) VALUES (:book_id, :owner_id, :user_id, :request_type)",
        book_id=book_id, owner_id=owner_id, user_id=request_user, request_type="borrow")

        #update book state to on hold
        db.execute("UPDATE books SET state=:state WHERE id=:id", state="on Hold",id=book_id)
        flash("you successfully requested a borrow")
        return redirect("/borrow")
    else:

        return render_template("borrow.html")



@app.route("/requests", methods=["GET", "POST"])
@login_required
def requests():

    if request.method =="POST":


        if not request.form.get("request_id"):
             flash("Must select a request to approve!")
             return redirect("/requests")

        #get the  request_id
        request_id = request.form.get("request_id")

        #for both return and borrow requests get the approval time.
        approval_time = datetime.date.today()

        #get the request info
        request_info = db.execute("SELECT book_id, user_id, request_type FROM requests WHERE id=:id", id=request_id)
        book_id  = request_info[0]["book_id"]
        requester_id  = request_info[0]["user_id"]

        #if i wanted to delete a pending my borrow or return request.
        if request.form.get("cancel"):
            db.execute("DELETE FROM requests WHERE id=:id", id=request_id)

            #only if the request was borrow we remove the hold from the book
            if request_info[0]["request_type"] == 'borrow':
                db.execute("UPDATE books SET state=:state WHERE id=:id", state='available',id=book_id)


        #if it is a borrow request
        if request.form.get("approve"):

            if not request.form.get("dispatch_date"):
                flash("Must specify a dispatch time!")
                return redirect("/requests")

            delivery_date = datetime.timedelta(days=int(request.form.get("dispatch_date"))) + approval_time
            #update the state of the request as approved
            db.execute("UPDATE requests SET state=:state, approval_time=:approval_time, delivery_date=:delivery_date WHERE id=:id",
             state="approved", approval_time=approval_time, delivery_date=delivery_date, id=request_id)




        #if it is a confirm return request
        if request.form.get("confirm"):
            db.execute("UPDATE requests SET state=:state, approval_time=:approval_time WHERE id=:id",
            state="approved", approval_time=approval_time, id=request_id)

            db.execute("UPDATE books SET state=:state WHERE id=:id", state="available",id=book_id)

            db.execute("INSERT INTO borrowed (user_id, operation, book_id, transacted) VALUES (:user_id, :operation, :book_id, :transacted)", user_id=requester_id,
             operation=-1, book_id=book_id, transacted=approval_time)


            send_email( requester_id, book_id, operation="returned")




        return redirect("/requests")
        #user should receive an email.
        #loan period will start counting one  day from dispatch time.


    else:
        #Incoming pending borrow requests
        in_rows = db.execute("SELECT requests.id, users.username, books.title, books.subtitle, books.authors, books.publishedDate \
        , books.state, requests.time, requests.state as 'Requeststate' FROM requests JOIN books ON books.id=requests.book_id JOIN users ON  users.id=requests.user_id  \
         WHERE owner_id=:owner_id AND requests.state='pending' AND requests.request_type='borrow'  ", owner_id=session["user_id"])

        #incoming pending return requests
        rn_rows = db.execute("SELECT requests.id,  users.username, books.title, books.subtitle, books.authors, books.publishedDate\
        , requests.time, requests.state as 'Requeststate', requests.delivery_date FROM requests JOIN books ON books.id=requests.book_id JOIN users ON  users.id=requests.user_id  \
          WHERE owner_id=:owner_id AND requests.state='pending' AND requests.request_type='Return' ", owner_id=session["user_id"])


        #your pending requests
        out_rows = db.execute("SELECT requests.id, users.username, requests.request_type, books.title, books.subtitle, books.authors, books.publishedDate \
        , books.lendfor as 'loan period', requests.time, requests.state as 'Requeststate', requests.delivery_date FROM requests JOIN books ON books.id=requests.book_id \
        JOIN users ON  users.id=requests.owner_id WHERE user_id=:user_id AND requests.state='pending'",user_id=session["user_id"])

        return render_template("requests.html",in_rows=in_rows, out_rows=out_rows, rn_rows=rn_rows)



@app.route("/history", methods=["GET"])
@login_required
def history():


    #Incoming approved requests
    approved_reqs = db.execute("SELECT requests.request_type,  books.title, books.subtitle, books.authors, \
     users.username, requests.time, requests.approval_time, requests.delivery_date FROM requests JOIN books ON books.id=requests.book_id \
     JOIN users ON users.id=requests.user_id WHERE requests.state=:state AND  owner_id=:owner_id ", state='approved', owner_id=session["user_id"])


    #your approved requests
    your_reqs = db.execute("SELECT requests.request_type,  books.title, books.subtitle, books.authors,\
    users.username, requests.time, requests.approval_time, requests.delivery_date FROM requests JOIN books ON books.id=requests.book_id \
    JOIN users ON users.id=requests.owner_id WHERE requests.state=:state AND  user_id=:user_id",state='approved', user_id=session["user_id"])


    return render_template("History.html", approved_reqs=approved_reqs, your_reqs=your_reqs)



@app.route("/searchresults")
@login_required
def searchresults():

    if request.args.get("title") == None or request.args.get("subtitle") == None:
        abort(500)

    else:
        title = request.args.get("title")
        subtitle = request.args.get("subtitle")

        #in case display all
        if not title and  not subtitle :
            results = db.execute("SELECT books.id, username, title, subtitle, authors, publishedDate, lendfor, review, notes, state  FROM mycollection JOIN books ON mycollection.book_id=books.id \
            JOIN users on users.id=mycollection.user_id WHERE user_id!=:user_id", user_id=session["user_id"])

        #some books might not have a subtitle, i.e empty
        else:
            results = db.execute("SELECT books.id,  username, title, subtitle, authors, publishedDate, lendfor, review, notes, state  FROM mycollection JOIN books ON mycollection.book_id=books.id \
            JOIN users on users.id=mycollection.user_id WHERE user_id!=:user_id  AND title=:title AND subtitle=:subtitle", user_id=session["user_id"], title=title, subtitle=subtitle)

        return jsonify(results)


@app.route("/search")
@login_required
def search():

    if request.args.get("q") == None:
        abort(500)

    #searching upon different users own-collections except the current user's
    else:
        #for conveninece
        bookq = request.args.get("q").strip()
        #split on every space
        tmp = bookq.split()
        #if multiple words
        if len(tmp) > 1:
            title=""
            subtitle=""
            tmps = tmp[0]
            for i in range(1, len(tmp)):

                tmps += " "+tmp[i]
                rows = db.execute("SELECT * FROM mycollection JOIN books ON mycollection.book_id=books.id WHERE user_id!=:user_id AND title LIKE :title  GROUP BY authors ",
                user_id=session["user_id"], title=tmps+"%")
                #possibly hitting a subtitle or book doesn't exist in db.
                if len(rows) == 0:
                    title  = " ".join(tmp[:i])
                    subtitle = " ".join(tmp[i:])
                    break

            if subtitle != "":

                rows = db.execute("SELECT * FROM mycollection JOIN books ON mycollection.book_id=books.id WHERE user_id!=:user_id AND title LIKE :title AND subtitle LIKE :subtitle  GROUP BY authors",
                 user_id=session["user_id"], title=title+"%", subtitle=subtitle+"%")

                if len(rows) !=0:
                    return jsonify(rows)
                else:
                    #book doesn't exist
                    return jsonify([])

            #only title searched
            else:
                return jsonify(rows)

        #if one word
        else:
            rows = db.execute("SELECT * FROM mycollection JOIN books ON mycollection.book_id=books.id WHERE user_id!=:user_id AND title LIKE :title GROUP BY authors",
            user_id=session["user_id"], title=bookq+"%")

            return jsonify(rows)


@app.route("/login", methods=["GET", "POST"])
def login():
    #forget any user id
    session.clear();

    if request.method == "POST":

        #ensure proper usage
        if not request.form.get("username_mail"):
            return render_template("login.html", error=" Must provide username or email!")

        if not request.form.get("password"):
            return render_template("login.html", error=" Must provide password")

        #login with email is enabled too.
        rows = db.execute("SELECT * FROM users WHERE username=:username OR email=:email", username=request.form.get("username_mail"),
        email=request.form.get("username_mail"))

        #check if user exists
        if len(rows) != 1:
            return render_template("login.html", error=" User doesn't exist!")

        elif not check_password_hash(rows[0]["password"], request.form.get("password")):
            return render_template("login.html", error=" Incorrect password!")

        else:
            #remember user id
            session["user_id"] = rows[0]["id"]
            flash("you successfully logged in")
            return redirect("/")
    else:
        return render_template("login.html")



@app.route("/logout")
def logout():

    #forget any user ID
    session.clear()
    #redirect to the login page
    return redirect("/login")


@app.route("/register", methods=["GET", "POST"])
def register():


    if request.method == "POST":

        #ensure proper entry of fields
        if not request.form.get("username") :
            #I render the template because I want to send a message
            flash("Error:  must provide username!")
            return redirect("/register")

        if not request.form.get("email") :
            flash("Error: not valid email!")
            return redirect("/register")

        #server side email validation
        if validate(request.form.get("email")) == None:
            flash("Error: not valid email!")
            return redirect("/register")

        if not request.form.get("password"):
             flash("Error: must provide password!")
             return redirect("/register")


        if len(request.form.get("password")) < 8:
            flash("Error: Password is too short!")
            return redirect("/register")

        if  request.form.get("password") != request.form.get("confirmation"):
            flash("Error: Passwords don't match!")
            return redirect("/register")


        #check if username an the email already exist
        username = request.form.get("username")
        email = request.form.get("email")

        rows = db.execute("SELECT * FROM users WHERE username=:username OR email=:email", username=username, email=email)
        #username already taken
        if len(rows) != 0:
            flash("Error: Username or Email already exists!")
            return redirect("/register")

        #if new registrant into our website
        else:
             #prepare password
            hashed_password = generate_password_hash(request.form["password"])

            #insert new user to our database
            session["user_id"] = db.execute("INSERT INTO users (username, email, password) VALUES (:username, :email, :password)",username=username,
            password=hashed_password, email=email)
            flash("you have registered successfully!")
            return redirect("/")

    #if GET
    else:
        return render_template("register.html")

@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():

    if request.method == "POST":

        #ensure proper usage
        if not request.form.get("email") or not validate(request.form.get("email")) :
            flash("not valid email!")
            return redirect("forgot_password")

        #ensure email exists in our database
        trgt_email = db.execute("SELECT * FROM users WHERE email=:email", email=request.form.get("email"))

        if len(trgt_email) != 1:
            flash("email doesn't exit")
            return redirect("/forgot_password")


        # inspired by Robert Picard article on Patterns for handling users
        #generate the unique token
        token = ts.dumps(request.form.get("email") ,salt="password_reset_key")
        #generate the url
        url_unique = "http://127.0.0.1:5000" +  url_for("change_password") + token

        #prepare reset password email.
        msg = Message("Reset Password",sender=app.config["MAIL_USERNAME"],recipients=[request.form.get("email")])
        msg.body =  "Hello there, you have requested a new password for your Book Stall account. \
        please click this link to reset your password. "+  url_unique

        #no asynchronous send email thread.
        mail.send(msg)
        flash("reset email was sent.")
        return redirect("/forgot_password")

    else:
        return render_template("forgot_password.html")

@app.route("/change_password/", methods=["POST"])
@app.route("/change_password/<token>")
def change_password(token=None):

    if request.method == "POST":

        if not request.form.get("password"):
            return render_template("change_password.html", error=" Must enter a Password!")

        if len(request.form.get("password")) < 8:
            return render_template("change_password.html", error=" Password is too short!")

        if  request.form.get("password") != request.form.get("confirmation"):
            return render_template("change_password.html", error=" Passwords don't match!")

        #email is already checked prepare password
        hashed_password = generate_password_hash(request.form["password"])

        db.execute("UPDATE users SET password=:password WHERE email=:email", password=hashed_password, email=session["email"])


        return redirect("/login")
    else:

        try:
            #validate the token ith maximum valid time of 5 minutes.
            email_ = ts.loads(token, salt="password_reset_key", max_age=300)

        except SignatureExpired:
            flash("This link has expried, please send another recovery email to change your password ")
            return redirect("/forgot_password")

        except (BadTimeSignature, BadSignature):
            flash("This link is incorrect, please send another recovery email to change your password ")
            return redirect("/forgot_password")

        #token is validate, then email is correct
        session["email"] = email_
        return render_template("change_password.html")
