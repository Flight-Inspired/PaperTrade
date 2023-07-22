import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Add a custom global function to the Jinja environment


@app.context_processor
def inject_helpers():
    return {
        "lookup": lookup,
        "usd": usd,
    }


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks."""
    # Get user ID
    user_id = session["user_id"]

    # Get user's cash balance
    user_cash = db.execute("SELECT cash FROM users WHERE id = ?", user_id)[0]["cash"]

    # Get user's portfolio data (symbol, total shares, total value)
    portfolio_data = db.execute("""
        SELECT symbol, SUM(shares) AS total_shares, ROUND(SUM(shares * price), 2) AS total_value
        FROM transactions
        WHERE user_id = ?
        GROUP BY symbol
        HAVING total_shares > 0
    """, user_id)

    # Calculate the total value of the portfolio (stocks' total value + cash)
    total_portfolio_value = sum(float(item["total_value"]) for item in portfolio_data) + user_cash

    # Render the 'index.html' template with the portfolio data
    return render_template("index.html", portfolio_data=portfolio_data, cash=user_cash, total_value=total_portfolio_value)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock."""
    if request.method == "POST":
        # Get user input from the form
        symbol = request.form.get("symbol")
        shares = request.form.get("shares")

        # Ensure the user entered a stock symbol
        if not symbol:
            return apology("Please enter a stock symbol", 400)

        # Ensure the user entered a positive integer for shares
        try:
            shares = int(shares)
            if shares <= 0:
                raise ValueError()
        except ValueError:
            return apology("Please enter a positive integer for shares", 400)

        # Check if the stock symbol exists and fetch stock information
        stock = lookup(symbol)
        if not stock:
            return apology("Stock symbol not found", 400)

        # Calculate the total cost of the purchase
        total_cost = stock["price"] * shares

        # Get the user's current cash balance from the 'users' table
        user_id = session["user_id"]
        user = db.execute("SELECT cash FROM users WHERE id = ?", user_id)

        # Check if the user can afford the purchase
        cash_balance = user[0]["cash"]
        if cash_balance < total_cost:
            return apology("Insufficient funds", 400)

        # Deduct the total cost from the user's cash balance
        new_cash_balance = cash_balance - total_cost

        # Update the user's cash balance in the 'users' table
        db.execute("UPDATE users SET cash = ? WHERE id = ?", new_cash_balance, user_id)

        # Record the purchase transaction in the 'transactions' table
        db.execute("INSERT INTO transactions (user_id, symbol, shares, price) VALUES (?, ?, ?, ?)",
                   user_id, symbol, shares, stock["price"])

        # Redirect the user to the home page
        return redirect("/")

    else:
        # Render the 'buy.html' template for the GET request
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    # Get user ID
    user_id = session["user_id"]

    # Get all transactions for the user, ordered by timestamp (latest first)
    transactions = db.execute("""
        SELECT symbol, shares, price, timestamp,
        CASE WHEN shares > 0 THEN 'BUY' ELSE 'SELL' END AS action
        FROM transactions
        WHERE user_id = ?
        ORDER BY timestamp DESC
    """, user_id)

    # Render the 'history.html' template with the transaction history data
    return render_template("history.html", transactions=transactions)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 400)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 400)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 400)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":
        symbol = request.form.get("symbol")

        # Use the `lookup` function to get stock information
        stock = lookup(symbol)
        if not stock:
            return apology("Stock symbol not found", 400)

        # Render the 'quoted.html' template with the stock information
        return render_template("quoted.html", symbol=symbol, name=stock["name"], price=stock["price"])
    else:
        # Render the 'quote.html' template for the GET request
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":
        # Ensure username was submitted
        username = request.form.get("username")
        if not username:
            return apology("must provide username", 400)

        # Ensure password was submitted
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")
        if not password or not confirmation:
            return apology("must provide password and confirmation", 400)

        # Ensure password and confirmation match
        if password != confirmation:
            return apology("passwords do not match", 400)

        # Check if the username already exists in the database
        existing_users = db.execute("SELECT * FROM users WHERE username = ?", username)
        if len(existing_users) > 0:
            return apology("username already exists", 400)

        # Hash the user's password
        hashed_password = generate_password_hash(password)

        # Insert the new user into the users table
        db.execute("INSERT INTO users (username, hash) VALUES (?, ?)", username, hashed_password)

        # Redirect user to the login page
        return redirect("/login")

    # If the request method is GET, render the registration form
    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock."""
    if request.method == "POST":
        # Get user input from the form
        symbol = request.form.get("symbol")
        shares = int(request.form.get("shares"))

        # Validate the user input and fetch stock information
        stock = lookup(symbol)
        if not stock:
            return apology("Stock symbol not found", 400)

        user_id = session["user_id"]
        user = db.execute("SELECT cash FROM users WHERE id = ?", user_id)
        cash_balance = user[0]["cash"]

        # Check if the user owns that many shares of the stock
        owned_shares = db.execute(
            "SELECT SUM(shares) as total_shares FROM transactions WHERE user_id = ? AND symbol = ?",
            user_id, symbol
        )
        if not owned_shares or shares > owned_shares[0]["total_shares"]:
            return apology("You don't own that many shares of the stock", 400)

        # Calculate the total value of the sold shares based on the current price
        total_value = stock["price"] * shares

        # Update the user's cash balance in the 'users' table
        new_cash_balance = cash_balance + total_value
        db.execute("UPDATE users SET cash = ? WHERE id = ?", new_cash_balance, user_id)

        # Record the sale transaction in the 'transactions' table
        db.execute("INSERT INTO transactions (user_id, symbol, shares, price) VALUES (?, ?, ?, ?)",
                   user_id, symbol, -shares, stock["price"])

        # Redirect the user to the home page
        return redirect("/")

    else:
        # Fetch the list of owned stock symbols for the select menu
        user_id = session["user_id"]
        stocks = db.execute(
            "SELECT symbol FROM transactions WHERE user_id = ? GROUP BY symbol HAVING SUM(shares) > 0",
            user_id
        )

        # As `db.execute` returns a list of dictionaries, you can directly use it in the template
        return render_template("sell.html", stocks=stocks)


@app.route("/deposit", methods=["GET", "POST"])
@login_required
def deposit():
    """Allow users to add additional cash to their account."""
    if request.method == "POST":
        # Get the amount of cash to be added from the form
        try:
            amount = float(request.form.get("amount"))
        except ValueError:
            return apology("Invalid amount", 400)

        # Ensure the amount is a positive number
        if amount <= 0:
            return apology("Amount must be a positive number", 400)

        # Get the user ID
        user_id = session["user_id"]

        # Get the current cash balance of the user
        user_cash = db.execute("SELECT cash FROM users WHERE id = ?", user_id)[0]["cash"]

        # Calculate the new cash balance after the addition
        new_cash_balance = user_cash + amount

        # Update the user's cash balance in the database
        db.execute("UPDATE users SET cash = ? WHERE id = ?", new_cash_balance, user_id)

        # Redirect the user back to the index page with a success message
        flash(f"Successfully added ${amount:.2f} to your account!", "success")
        return redirect("/")
    else:
        return render_template("deposit.html")
