"""
Database models and operations for a drink management system using SQLAlchemy and FastAPI.

This module provides functions to manage postpaid and prepaid users, handle drink transactions,
log money transfers, and generate statistics. It includes table creation, user CRUD operations,
transaction logging, drink recording, and utility functions for drink statistics.

Constants:
    DRINK_COST (int): Cost of a drink in cents.

Functions:
    _log_transaction(user_id, user_is_postpaid, ...): Log a user's money transaction.
    create_postpaid_user(username): Create a new postpaid user.
    get_postpaid_user(user_id): Retrieve a postpaid user's info by ID.
    get_postpaid_user_by_username(username): Retrieve a postpaid user by username.
    set_postpaid_user_money(user_id, money): Set a postpaid user's balance.
    drink_postpaid_user(user_id, drink_type): Deduct drink cost and record a drink for postpaid user
    toggle_activate_postpaid_user(user_id): Toggle activation status of a postpaid user.
    payup_postpaid_user(current_user_id, payup_user_id, money_cent): Transfer money btw. post users.
    get_prepaid_user(user_id): Retrieve a prepaid user's info by ID.
    get_prepaid_user_by_username(username): Retrieve a prepaid user by username.
    create_prepaid_user(prepaid_username, postpaid_user_id, start_money): Create a new prepaid user.
    drink_prepaid_user(user_db_id): Process a prepaid drink transaction.
    toggle_activate_prepaid_user(user_id): Toggle activation status of a prepaid user.
    set_prepaid_user_money(user_id, money, postpaid_user_id): Set prepaid user's balance and link.
    del_user_prepaid(user_id): Delete a prepaid user.
    get_last_drink(user_id, user_is_postpaid, max_since_seconds): Get last drink within time window.
    revert_last_drink(user_id, user_is_postpaid, drink_id, drink_cost): Revert a drink and refund.
    update_drink_type(user_id, user_is_postpaid, drink_id, drink_type): Update drink type for drink.
    get_most_used_drinks(user_id, user_is_postpaid, limit): Get most used drinks for a user.
    get_stats_drink_types(): Get statistics of drink types.

    HTTPException: For database errors, not found, or forbidden actions.
"""
import os
import secrets
import datetime
import random
from sqlalchemy import create_engine, text
from fastapi import HTTPException

from dotenv import load_dotenv

load_dotenv()
DATABASE_FILE = os.getenv("DATABASE_FILE", "test.db")
DATABASE_URL = "sqlite:///" + str(DATABASE_FILE)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

DRINK_COST = 100  # cent

with engine.connect() as conn:
    # Create a table for postpaid users
    conn.execute(text("""
                      CREATE TABLE IF NOT EXISTS users_postpaid (
                          id INTEGER PRIMARY KEY AUTOINCREMENT,
                          username TEXT NOT NULL UNIQUE,
                          money INT DEFAULT 0,
                          activated BOOLEAN DEFAULT 0,
                          last_drink TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                          survey BOOLEAN DEFAULT 0
                        )
                      """))

    # create a table for every prepaid user
    conn.execute(text("""
                      CREATE TABLE IF NOT EXISTS users_prepaid (
                          id INTEGER PRIMARY KEY AUTOINCREMENT,
                          username TEXT NOT NULL UNIQUE,
                          user_key TEXT NOT NULL UNIQUE,
                          postpaid_user_id INTEGER NOT NULL,
                          money INT DEFAULT 0,
                          activated BOOLEAN DEFAULT 1,
                          last_drink TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                          FOREIGN KEY (postpaid_user_id) REFERENCES users_postpaid(id)
                      )
                      """))

    # create a table for every push on the drink button
    conn.execute(text("""
                      CREATE TABLE IF NOT EXISTS drinks (
                          id INTEGER PRIMARY KEY AUTOINCREMENT,
                          postpaid_user_id INTEGER,
                          prepaid_user_id INTEGER,
                          timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                          drink_type INTEGER DEFAULT 1,
                          FOREIGN KEY (postpaid_user_id) REFERENCES users_postpaid(id),
                          FOREIGN KEY (prepaid_user_id) REFERENCES users_prepaid(id),
                          FOREIGN KEY (drink_type) REFERENCES drink_types(id)
                      )
                      """))

    # create a table for every money transaction
    conn.execute(text("""
                      CREATE TABLE IF NOT EXISTS transactions (
                          id INTEGER PRIMARY KEY AUTOINCREMENT,
                          postpaid_user_id INTEGER,
                          prepaid_user_id INTEGER,
                          timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                          previous_money INT NOT NULL,
                          new_money INT NOT NULL,
                          delta_money INT NOT NULL,
                          description TEXT,
                          FOREIGN KEY (postpaid_user_id) REFERENCES users_postpaid(id),
                          FOREIGN KEY (prepaid_user_id) REFERENCES users_prepaid(id)
                      )
                      """))
    
    # create a table for drink types
    conn.execute(text("""
                      CREATE TABLE IF NOT EXISTS drink_types (
                          id INTEGER PRIMARY KEY AUTOINCREMENT,
                            drink_name TEXT NOT NULL UNIQUE,
                            icon TEXT NOT NULL,
                            quantity INT DEFAULT 0
                      )
                      """))
    conn.execute(text("""
                      INSERT OR IGNORE INTO drink_types (id, drink_name, icon, quantity) VALUES
                        (1, 'Sonstiges', 'sonstiges.png', 0),
                        (2, 'Paulaner Spezi', 'paulaner_spezi.png', 0),
                        (3, 'Paulaner Limo Orange', 'paulaner_limo_orange.png', 0),
                        (4, 'Paulaner Limo Zitrone', 'paulaner_limo_zitrone.png', 0),
                        (5, 'Mio Mate Original', 'mio_mate_original.png', 0),
                        (6, 'Mio Mate Ginger', 'mio_mate_ginger.png', 0),
                        (7, 'Mio Mate Pomegranate', 'mio_mate_pomegranate.png', 0),
                        (8, 'Club Mate', 'club_mate.png', 0)
                      """))
    conn.commit()



def _log_transaction(
        user_id: int,
        user_is_postpaid: bool,
        previous_money_cent = None,
        new_money_cent = None,
        delta_money_cent = None,
        description = None
    ):
    """
    Logs a transaction for a user, recording changes in their account balance.

    Depending on whether the user is postpaid or prepaid, retrieves the previous balance if not
    provided, calculates the new balance and delta if necessary, and inserts a transaction record
    into the database.

    Args:
        user_id (int): The ID of the user for whom the transaction is being logged.
        user_is_postpaid (bool): True if the user is postpaid, False if prepaid.
        previous_money_cent (Optional[int], default=None): The user's previous balance in cents.
            If None, it is fetched from the database.
        new_money_cent (Optional[int], default=None): The user's new balance in cents. If None,
            it is calculated using delta_money_cent.
        delta_money_cent (Optional[int], default=None): The change in balance in cents. If None,
            it is calculated using new_money_cent.
        description (Optional[str], default=None): A description of the transaction.

    Raises:
        HTTPException: If the user is not found, if both new_money_cent and delta_money_cent are
            missing, or if the transaction could not be logged.

    Returns:
        int: The ID of the newly created transaction record.
    """
    if previous_money_cent is None:
        if user_is_postpaid:
            t_get_prev_money = text("SELECT money FROM users_postpaid WHERE id = :id")
        else:
            t_get_prev_money = text("SELECT money FROM users_prepaid WHERE id = :id")
        with engine.connect() as connection:
            res = connection.execute(t_get_prev_money, {"id": user_id}).fetchone()
            if res:
                previous_money_cent = int(res[0])
            else:
                raise HTTPException(status_code=404, detail="User not found")
    if new_money_cent is None and delta_money_cent is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Either new_money or delta_money "
                "must be provided, not both"
            )
        )
    if new_money_cent is None and delta_money_cent is not None:
        new_money_cent = previous_money_cent + delta_money_cent
    elif delta_money_cent is None and new_money_cent is not None:
        delta_money_cent = new_money_cent - previous_money_cent

    # here we definitly have all the variables
    if user_is_postpaid:
        t = text("INSERT INTO transactions (postpaid_user_id, previous_money, new_money, delta_money, description) VALUES (:user_id, :previous_money, :new_money, :delta_money, :description)")
    else:
        t = text("INSERT INTO transactions (prepaid_user_id, previous_money, new_money, delta_money, description) VALUES (:user_id, :previous_money, :new_money, :delta_money, :description)")
    with engine.connect() as connection:
        result = connection.execute(
            t,
            {
                "user_id": user_id,
                "previous_money": previous_money_cent,
                "new_money": new_money_cent,
                "delta_money": delta_money_cent,
                "description": description
            }
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=500, detail="Failed to log transaction")
        connection.commit()

    return result.lastrowid

def create_postpaid_user(username: str):
    """
    Creates a new postpaid user with the given username in the users_postpaid table.
    Args:
        username (str): The username of the user to be created.
    Raises:
        HTTPException: If the user already exists (status_code=400).
        HTTPException: If the user could not be created due to a database error (status_code=500).
    Returns:
        int: The ID of the newly created user.
    """

    print(f"create_postpaid_user: {username}")
    t_insert = text("INSERT INTO users_postpaid (username) VALUES (:username)")
    with engine.connect() as connection:
        t_select = text("SELECT * FROM users_postpaid WHERE username = :username")
        if connection.execute(t_select, {"username": username}).fetchone():
            raise HTTPException(status_code=400, detail="User already exists")
        try:
            res = connection.execute(t_insert, {"username": username})
            if res.rowcount == 0:
                raise HTTPException(status_code=500, detail="Failed to create user")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}") from e
        connection.commit()

    return res.lastrowid

def get_postpaid_user(user_id: int):
    """
    Retrieve a postpaid user's information from the database by user ID.
    Args:
        user_id (int): The unique identifier of the user to retrieve.
    Returns:
        dict: A dictionary containing the user's id, username, money, activated status, and last_drink timestamp.
    Raises:
        HTTPException: If no user with the given ID is found, raises a 404 HTTPException.
    """

    t = text("SELECT id, username, money, activated, last_drink FROM users_postpaid WHERE id = :id")
    user_db = {}
    with engine.connect() as connection:
        result = connection.execute(t, {"id": user_id}).fetchone()
        if result:
            user_db["id"] = result[0]
            user_db["username"] = result[1]
            user_db["money"] = result[2]
            user_db["activated"] = result[3]
            user_db["last_drink"] = result[4]
        else:
            raise HTTPException(status_code=404, detail="User not found")
    return user_db

def get_postpaid_user_by_username(username: str):
    """
    Retrieve a postpaid user from the database by their username.
    Args:
        username (str): The username of the user to retrieve.
    Returns:
        dict: A dictionary containing the user's id, username, money, activated status, and last_drink timestamp.
    Raises:
        HTTPException: If no user with the given username is found, raises a 404 HTTPException.
    """

    t = text("SELECT id, username, money, activated, last_drink FROM users_postpaid WHERE username = :username")
    user_db = {}
    with engine.connect() as connection:
        result = connection.execute(t, {"username": username}).fetchone()
        if result:
            user_db["id"] = result[0]
            user_db["username"] = result[1]
            user_db["money"] = result[2]
            user_db["activated"] = result[3]
            user_db["last_drink"] = result[4]
        else:
            raise HTTPException(status_code=404, detail="User not found")
    return user_db

def set_postpaid_user_money(user_id: int, money: float):
    """
    Updates the 'money' value for a postpaid user in the database.
    Args:
        user_id (int): The ID of the user whose balance is to be updated.
        money (float): The new balance to set for the user.
    Raises:
        HTTPException: If no user with the given ID is found (404 error).
    Returns:
        int: The number of rows affected by the update operation.
    """

    _log_transaction(
        user_id,
        user_is_postpaid=True,
        new_money_cent=money,
        description="Set money manually via Admin UI"
    )
    t = text("UPDATE users_postpaid SET money = :money WHERE id = :id")
    with engine.connect() as connection:
        result = connection.execute(t, {"id": user_id, "money": money})
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        connection.commit()
    return result.rowcount

def drink_postpaid_user(user_id: int, drink_type: int = 1):
    """
    Deducts 100 units from the specified postpaid user's balance and records a drink entry.
    Args:
        user_id (int): The ID of the postpaid user.
    Raises:
        HTTPException: If the user is not found (404) or if the drink entry could not be created (500).
    Returns:
        int: The number of rows affected by the drink entry insertion (should be 1 on success).
    """

    activated = get_postpaid_user(user_id)["activated"]
    if not activated:
        raise HTTPException(status_code=403, detail="User not activated")

    prev_money = get_postpaid_user(user_id)["money"]
    _log_transaction(
        user_id=user_id,
        user_is_postpaid=True,
        previous_money_cent=prev_money,
        delta_money_cent=-DRINK_COST,
        description="Drink button pressed"
    )
    t = text("UPDATE users_postpaid SET money = :money, last_drink = CURRENT_TIMESTAMP WHERE id = :id")
    with engine.connect() as connection:
        result = connection.execute(t, {"id": user_id, "money": prev_money - DRINK_COST})
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        connection.commit()

    t_without_drink_type = text("INSERT INTO drinks (postpaid_user_id, timestamp) VALUES (:postpaid_user_id, CURRENT_TIMESTAMP)")
    t_with_drink_type = text("INSERT INTO drinks (postpaid_user_id, timestamp, drink_type) VALUES (:postpaid_user_id, CURRENT_TIMESTAMP, :drink_type)")

    with engine.connect() as connection:
        if not drink_type:
            result = connection.execute(t_without_drink_type, {"postpaid_user_id": user_id})
        else:
            result = connection.execute(t_with_drink_type, {"postpaid_user_id": user_id, "drink_type": drink_type})
        if result.rowcount == 0:
            raise HTTPException(status_code=500, detail="Failed to create drink entry")
        connection.commit()
    return result.rowcount

def toggle_activate_postpaid_user(user_id: int):
    """
    Toggles the 'activated' status of a postpaid user in the database.
    Args:
        user_id (int): The ID of the user whose activation status should be toggled.
    Returns:
        int: The number of rows affected by the update operation.
    Raises:
        HTTPException: If no user with the given ID is found (404 error).
    """
    prev_activated = get_postpaid_user(user_id)["activated"]
    t = text("UPDATE users_postpaid SET activated = :activated WHERE id = :id")
    with engine.connect() as connection:
        result = connection.execute(t, {"id": user_id, "activated": not prev_activated})
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        connection.commit()
    return result.rowcount

def payup_postpaid_user(current_user_id: int, payup_user_id: int, money_cent: int):
    """
    Transfers a specified amount of money (in cents) from one postpaid user to another.
    Args:
        current_user_id (int): ID of the user paying the money.
        payup_user_id (int): ID of the user receiving the money.
        money_cent (int): Amount of money to transfer, in cents.
    Raises:
        HTTPException: If either user is not activated or not found in the database.
    """
    current_user = get_postpaid_user(current_user_id)
    if not current_user["activated"]:
        raise HTTPException(status_code=403, detail="Current user not activated")
    payup_user = get_postpaid_user(payup_user_id)
    if not payup_user["activated"]:
        raise HTTPException(status_code=403, detail="Payup user not activated")

    # subtract money from current user
    t = text("UPDATE users_postpaid SET money = money - :money WHERE id = :id")
    with engine.connect() as connection:
        result = connection.execute(t, {"id": current_user_id, "money": money_cent})
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Current user not found")
        connection.commit()
    _log_transaction(
        user_id=current_user_id,
        user_is_postpaid=True,
        previous_money_cent=current_user["money"],
        delta_money_cent=-money_cent,
        description=f"Payup to user {payup_user_id}"
    )

    # add money to payup user
    t = text("UPDATE users_postpaid SET money = money + :money WHERE id = :id")
    with engine.connect() as connection:
        result = connection.execute(t, {"id": payup_user_id, "money": money_cent})
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Payup user not found")
        connection.commit()
    _log_transaction(
        user_id=payup_user_id,
        user_is_postpaid=True,
        previous_money_cent=payup_user["money"],
        new_money_cent=payup_user["money"] + money_cent,
        delta_money_cent=money_cent,
        description=f"Received payup from user {current_user_id}"
    )

def get_prepaid_user(user_id: int):
    """
    Retrieve a prepaid user from the database by user ID.
    Args:
        user_id (int): The ID of the prepaid user to retrieve.
    Returns:
        dict: A dictionary containing the user's information with keys:
            - "id": User's ID
            - "username": User's username
            - "user_key": User's unique key
            - "postpaid_user_id": Linked postpaid user ID (if any)
            - "money": User's prepaid balance
            - "activated": Activation status
            - "last_drink": Timestamp of the user's last drink
    Raises:
        HTTPException: If no user with the given ID is found (status code 404).
    """
    t = text("SELECT id, username, user_key, postpaid_user_id, money, activated, last_drink FROM users_prepaid WHERE id = :id")
    user_db = {}
    with engine.connect() as connection:
        result = connection.execute(t, {"id": user_id}).fetchone()
        if result:
            user_db["id"] = result[0]
            user_db["username"] = result[1]
            user_db["user_key"] = result[2]
            user_db["postpaid_user_id"] = result[3]
            user_db["money"] = result[4]
            user_db["activated"] = result[5]
            user_db["last_drink"] = result[6]
        else:
            raise HTTPException(status_code=404, detail="User not found")
    return user_db

def get_prepaid_user_by_username(username: str):
    """
    Retrieve a prepaid user by username.
    Args:
        username (str): The username to look up.
    Returns:
        dict: User info (id, username, user_key, postpaid_user_id, money, activated, last_drink).
    Raises:
        HTTPException: If user not found (404).
    """
    t = text("SELECT id, username, user_key, postpaid_user_id, money, activated, last_drink FROM users_prepaid WHERE username = :username")
    user_db = {}
    with engine.connect() as connection:
        result = connection.execute(t, {"username": username}).fetchone()
        if result:
            user_db["id"] = result[0]
            user_db["username"] = result[1]
            user_db["user_key"] = result[2]
            user_db["postpaid_user_id"] = result[3]
            user_db["money"] = result[4]
            user_db["activated"] = result[5]
            user_db["last_drink"] = result[6]
        else:
            raise HTTPException(status_code=404, detail="User not found")
    return user_db

def create_prepaid_user(prepaid_username: str, postpaid_user_id: int, start_money: int = 0):
    """
    Create a new prepaid user in users_prepaid.
    Args:
        prepaid_username (str): Username for the new prepaid user.
        postpaid_user_id (int): Associated postpaid user ID.
        start_money (int, optional): Initial money for the prepaid user. Defaults to 0.
    Raises:
        HTTPException: If username exists (400) or user creation fails (500).
    Returns:
        int: ID of the new prepaid user.
    """
    prepaid_key = secrets.token_urlsafe(6)
    t = text("INSERT INTO users_prepaid (username, user_key, postpaid_user_id, money) VALUES (:username, :user_key, :postpaid_user_id, :start_money)")
    with engine.connect() as connection:

        # Check if user already exists in prepaid
        sel = text("SELECT * FROM users_prepaid WHERE username = :username")
        if connection.execute(sel, {"username": prepaid_username}).fetchone():
            raise HTTPException(status_code=400, detail="User already exists")

        result = connection.execute(
            t,
            {
                "username": str(prepaid_username),
                "user_key": str(prepaid_key),
                "postpaid_user_id": int(postpaid_user_id),
                "start_money": int(start_money),
            })
        if result.rowcount == 0:
            raise HTTPException(status_code=500, detail="Failed to create user")
        connection.commit()

    return result.lastrowid

def drink_prepaid_user(user_db_id: int):
    """
    Processes a prepaid drink transaction for a user.
    This function performs the following steps:
    1. Retrieves the prepaid user's information from the database.
    2. Checks if the user is activated; raises HTTP 403 if not.
    3. Checks if the user has enough money for a drink; raises HTTP 403 if not.
    4. Logs the transaction.
    5. Deducts the drink cost from the user's balance and updates the last drink timestamp.
    6. Inserts a new entry into the drinks table for the user.
    7. Commits all changes to the database.
    Args:
        user_db_id (int): The database ID of the prepaid user.
    Returns:
        int: The number of rows affected by the drink entry insertion.
    Raises:
        HTTPException: If the user is not activated (403), does not have enough money (403),
                       is not found (404), or if the drink entry could not be created (500).
    """
    user_dict = get_prepaid_user(user_db_id)
    if not user_dict["activated"]:
        raise HTTPException(status_code=403, detail="User not activated")

    prev_money = user_dict["money"]
    if prev_money < DRINK_COST:
        raise HTTPException(status_code=403, detail="Not enough money")

    _log_transaction(
        user_id=user_db_id,
        user_is_postpaid=False,
        previous_money_cent=prev_money,
        delta_money_cent=-DRINK_COST,
        description="Drink button pressed"
    )
    t = text("UPDATE users_prepaid SET money = :money, last_drink = CURRENT_TIMESTAMP WHERE id = :id")
    with engine.connect() as connection:
        result = connection.execute(t, {"id": user_db_id, "money": prev_money - DRINK_COST})
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        connection.commit()

    with engine.connect() as connection:
        t = text("INSERT INTO drinks (prepaid_user_id, timestamp) VALUES (:prepaid_user_id, CURRENT_TIMESTAMP)")
        result = connection.execute(t, {"prepaid_user_id": user_db_id})
        if result.rowcount == 0:
            raise HTTPException(status_code=500, detail="Failed to create drink entry")
        connection.commit()
    return result.rowcount

def toggle_activate_prepaid_user(user_id: int):
    """
    Toggles the 'activated' status of a prepaid user in the database.
    Args:
        user_id (int): The ID of the user whose activation status is to be toggled.
    Returns:
        int: The number of rows affected by the update operation.
    Raises:
        HTTPException: If no user with the given ID is found (404 error).
    """
    prev_activated = get_prepaid_user(user_id)["activated"]
    t = text("UPDATE users_prepaid SET activated = :activated WHERE id = :id")
    with engine.connect() as connection:
        result = connection.execute(t, {"id": user_id, "activated": not prev_activated})
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        connection.commit()
    return result.rowcount

def set_prepaid_user_money(user_id: int, money: int, postpaid_user_id: int):
    """
    Updates the prepaid user's money and associated postpaid user ID in the database.
    Args:
        user_id (int): The ID of the prepaid user whose information is to be updated.
        money (int): The new amount of money (in cents) to set for the user.
        postpaid_user_id (int): The ID of the associated postpaid user.
    Raises:
        HTTPException: If the user with the given user_id is not found in the database.
    Returns:
        int: The number of rows affected by the last update operation.
    """
    t1 = text("UPDATE users_prepaid SET money = :money WHERE id = :id")
    t2 = text("UPDATE users_prepaid SET postpaid_user_id = :postpaid_user_id WHERE id = :id")
    _log_transaction(
        user_id=user_id,
        user_is_postpaid=False,
        new_money_cent=money,
        description="Set money manually via Admin UI"
    )
    with engine.connect() as connection:
        result = connection.execute(t1, {"id": user_id, "money": money})
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        result = connection.execute(t2, {"id": user_id, "postpaid_user_id": postpaid_user_id})
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        connection.commit()
    return result.rowcount

def del_user_prepaid(user_id: int):
    """
    Deletes a user's prepaid entry from the 'users_prepaid' table by user ID.
    Args:
        user_id (int): The ID of the user whose prepaid entry should be deleted.
    Raises:
        HTTPException: If no entry with the given user_id is found (404 Not Found).
    Returns:
        int: The number of rows deleted (should be 1 if successful).
    """
    t = text("DELETE FROM users_prepaid WHERE id = :id")
    with engine.connect() as connection:
        result = connection.execute(t, {"id": user_id})
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        connection.commit()
    return result.rowcount

def get_last_drink(user_id: int, user_is_postpaid: bool, max_since_seconds: int = 60):
    """
    Retrieve the most recent drink entry for a user within a specified time window.

    Args:
        user_id (int): The ID of the user whose last drink is to be retrieved.
        user_is_postpaid (bool): True if the user is postpaid, False if prepaid.
        max_since_seconds (int, optional): Max seconds since last drink. Defaults to 60.

    Returns:
        dict or None: Dict with 'id', 'timestamp', 'drink_type' if found within time window,
        else None.
    """
    if user_is_postpaid:
        t = text("SELECT id, timestamp, drink_type FROM drinks WHERE postpaid_user_id = :user_id ORDER BY timestamp DESC LIMIT 1")
    else:
        t = text("SELECT id, timestamp, drink_type FROM drinks WHERE prepaid_user_id = :user_id ORDER BY timestamp DESC LIMIT 1")

    with engine.connect() as connection:
        result = connection.execute(t, {"user_id": user_id}).fetchone()
        if not result:
            return None
        drink_id, timestamp, drink_type_id = result

    if timestamp:
        now = datetime.datetime.now(datetime.timezone.utc)
        last_drink_time = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        # Ensure both are offset-aware
        if last_drink_time.tzinfo is None:
            last_drink_time = last_drink_time.replace(tzinfo=datetime.timezone.utc)
        if (now - last_drink_time).total_seconds() > max_since_seconds:
            return None
        drink_obj = {"id": drink_id, "timestamp": timestamp, "drink_type_id": drink_type_id}
        if drink_type_id:
            drink_type_name, drink_type_icon = get_drink_type(drink_type_id)
            drink_obj["drink_type_name"] = drink_type_name
            drink_obj["drink_type_icon"] = drink_type_icon
        return drink_obj
    return None

def revert_last_drink(user_id: int, user_is_postpaid: bool, drink_id: int, drink_cost: int = DRINK_COST):
    """
    Reverts the last drink purchase for a user and refunds the drink cost.
    Args:
        user_id (int): The ID of the user whose drink is to be reverted.
        user_is_postpaid (bool): True if the user is postpaid, False if prepaid.
        drink_id (int): The ID of the drink to revert.
        drink_cost (int, optional): The cost of the drink in cents. Defaults to DRINK_COST.
    Raises:
        HTTPException: If the drink or user is not found in the database.
    Side Effects:
        - Deletes the drink record from the database.
        - Refunds the drink cost to the user's balance.
        - Logs the transaction.
    """
    if user_is_postpaid:
        del_t = text("DELETE FROM drinks WHERE postpaid_user_id = :user_id AND id = :drink_id")
        update_t = text("UPDATE users_postpaid SET money = money + :drink_cost WHERE id = :user_id")
        money_t = text("SELECT money FROM users_postpaid WHERE id = :user_id")
    else:
        del_t = text("DELETE FROM drinks WHERE prepaid_user_id = :user_id AND id = :drink_id")
        update_t = text("UPDATE users_prepaid SET money = money + :drink_cost WHERE id = :user_id")
        money_t = text("SELECT money FROM users_prepaid WHERE id = :user_id")

    with engine.connect() as connection:
        # Check if the drink exists
        drink_exists = connection.execute(del_t, {"user_id": user_id, "drink_id": drink_id}).rowcount > 0
        if not drink_exists:
            raise HTTPException(status_code=404, detail="Drink not found")

        # Revert the money
        prev_money = connection.execute(money_t, {"user_id": user_id}).fetchone()
        if not prev_money:
            raise HTTPException(status_code=404, detail="User not found")

        new_money = prev_money[0] + drink_cost
        connection.execute(update_t, {"user_id": user_id, "drink_cost": drink_cost})
        connection.commit()

        _log_transaction(
            user_id=user_id,
            user_is_postpaid=user_is_postpaid,
            previous_money_cent=prev_money[0],
            new_money_cent=new_money,
            delta_money_cent=drink_cost,
            description="Reverted last drink"
        )

def update_drink_type(user_id: int, user_is_postpaid: bool, drink_id, drink_type_id: int):
    """
    Updates the drink type for a specific drink associated with a user.
    Depending on whether the user is postpaid or prepaid, the function updates the `drink_type`
    field in the `drinks` table for the drink with the given `drink_id` and user association.
    Args:
        user_id (int): The ID of the user whose drink is being updated.
        user_is_postpaid (bool): Indicates if the user is postpaid (True) or prepaid (False).
        drink_id: The ID of the drink to update.
        drink_type (str): The new type to set for the drink.
    Raises:
        HTTPException: If no drink is found with the given criteria (404 Not Found).
    Returns:
        int: The number of rows affected by the update.
    """
    if user_is_postpaid:
        t = text("UPDATE drinks SET drink_type = :drink_type WHERE postpaid_user_id = :user_id AND id = :drink_id")
    else:
        t = text("UPDATE drinks SET drink_type = :drink_type WHERE prepaid_user_id = :user_id AND id = :drink_id")
    
    t_update_quantity = text("UPDATE drink_types SET quantity = quantity - 1 WHERE id = :drink_type_id")

    with engine.connect() as connection:
        result = connection.execute(t, {"user_id": user_id, "drink_id": drink_id, "drink_type": drink_type_id})
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Drink not found")
        
        result_quantity = connection.execute(t_update_quantity, {"drink_type_id": drink_type_id})
        if result_quantity.rowcount != 1:
            raise HTTPException(status_code=404, detail="Drink type not found")
        connection.commit()
    return result.rowcount

def get_drink_type(drink_id: int):
    t = text("SELECT drink_name, icon FROM drink_types WHERE id = :drink_id")
    with engine.connect() as connection:
        result = connection.execute(t, {"drink_id": drink_id}).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Drink type not found")
        return {"drink_name": result[0], "icon": result[1]}
    
def get_drink_type_by_name(drink_name: str):
    t = text("SELECT id, icon FROM drink_types WHERE drink_name = :drink_name")
    with engine.connect() as connection:
        result = connection.execute(t, {"drink_name": drink_name}).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Drink type not found")
        return {"drink_type_id": result[0], "icon": result[1]}
    
def add_drink_type(drink_name: str, icon: str, quantity: int = 0):
    t = text("INSERT INTO drink_types (drink_name, icon, quantity) VALUES (:drink_name, :icon, :quantity)")
    with engine.connect() as connection:
        result = connection.execute(t, {"drink_name": drink_name, "icon": icon, "quantity": quantity})
        if result.rowcount == 0:
            raise HTTPException(status_code=500, detail="Failed to add drink type")
        connection.commit()

def set_drink_type_quantity(drink_type_id: int, quantity: int):
    t = text("UPDATE drink_types SET quantity = :quantity WHERE id = :drink_type_id")
    with engine.connect() as connection:
        result = connection.execute(t, {"drink_type_id": drink_type_id, "quantity": quantity})
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Drink type not found")
        connection.commit()

def get_most_used_drinks(user_id: int, user_is_postpaid: bool, limit: int = 4):
    """
    Return up to `limit` most used drinks for a user, filling with random drinks if needed.
    Args:
        user_id (int): User's ID.
        user_is_postpaid (bool): True if postpaid, else prepaid.
        limit (int): Max drinks to return.
    Returns:
        list[dict]: Each dict has 'drink_type' and 'count'.
    """
    if user_is_postpaid:
        t = text("SELECT drink_type, count(drink_type) as count FROM drinks WHERE postpaid_user_id = :user_id AND drink_type != 1 GROUP BY drink_type ORDER BY count DESC LIMIT :limit")
    else:
        t = text("SELECT drink_type, count(drink_type) as count FROM drinks WHERE prepaid_user_id = :user_id AND drink_type != 1 GROUP BY drink_type ORDER BY count DESC LIMIT :limit")

    with engine.connect() as connection:
        result = connection.execute(t, {"user_id": user_id, "limit": limit}).fetchall()
        drinks = [{"drink_type_id": row[0], "count": row[1]} for row in result]

        available_drink_ids_text = text("SELECT id FROM drink_types")
        available_drinks = connection.execute(available_drink_ids_text).fetchall()
        available_drink_ids = [row[0] for row in available_drinks]
        if 1 in available_drink_ids:
            available_drink_ids.remove(1)

    while len(drinks) < limit:
        if not available_drink_ids:
            print("No more available drink types to fill up the drinks list")
            break
        random_drink = random.choice(available_drink_ids)
        if any(drink["drink_type_id"] == random_drink for drink in drinks):
            available_drink_ids.remove(random_drink)
            continue
        drinks.append({"drink_type_id": random_drink, "count": 0})

    for drink in drinks:
        drink_type_info = get_drink_type(drink["drink_type_id"])
        drink["drink_type"] = drink_type_info["drink_name"]
        drink["icon"] = drink_type_info["icon"]

    return drinks

def get_stats_drink_types():
    """
    Retrieves statistics on drink types from the database.
    Executes a SQL query to count the occurrences of each non-null drink type in the 'drinks' table,
    grouping and ordering the results by the count in descending order.
    Returns:
        list[dict]: A list of dictionaries, each containing 'drink_type' (str) and 'count' (int).
                    Returns an empty list if no results are found.
    """
    t = text("SELECT drink_type, count(drink_type) as count FROM drinks WHERE drink_type IS NOT NULL AND drink_type != 'None' GROUP BY drink_type ORDER BY count DESC")

    with engine.connect() as connection:
        result = connection.execute(t).fetchall()
        if not result:
            return []
        drinks = [{"drink_type_id": row[0], "count": row[1]} for row in result]

    for drink in drinks:
        drink_type_info = get_drink_type(drink["drink_type_id"])
        drink["drink_type"] = drink_type_info["drink_name"]
        drink["icon"] = drink_type_info["icon"]

    return drinks
