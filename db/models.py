"""
This module defines database models and utility functions for managing users and drinks in a beverage tracking application using SQLAlchemy and FastAPI.
Tables:
    - users_postpaid: Stores postpaid user accounts.
    - users_prepaid: Stores prepaid user accounts, linked to postpaid users.
    - drinks: Records drink transactions for both postpaid and prepaid users.
Functions:
    - create_postpaid_user(username: str) -> int:
        Creates a new postpaid user with the specified username. Raises HTTPException if the user already exists or if a database error occurs. Returns the ID of the newly created user.
    - get_postpaid_user(user_id: int) -> dict:
        Retrieves a postpaid user's information by their user ID. Returns a dictionary with user details. Raises HTTPException if the user is not found.
    - get_postpaid_user_by_username(username: str) -> dict:
        Retrieves a postpaid user's information by their username. Returns a dictionary with user details. Raises HTTPException if the user is not found.
    - set_postpaid_user_money(user_id: int, money: float) -> int:
        Updates the 'money' balance for a postpaid user. Raises HTTPException if the user is not found. Returns the number of rows affected.
    - drink_postpaid_user(user_id: int) -> int:
        Deducts 100 units from the specified postpaid user's balance and records a drink entry. Raises HTTPException if the user is not found or if the drink entry could not be created. Returns the number of rows affected by the drink entry insertion.
"""
import secrets
from sqlalchemy import create_engine, text
from fastapi import HTTPException

import os
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
                          drink_type TEXT,
                          FOREIGN KEY (postpaid_user_id) REFERENCES users_postpaid(id),
                          FOREIGN KEY (prepaid_user_id) REFERENCES users_prepaid(id)
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
        Depending on whether the user is postpaid or prepaid, retrieves the previous balance if not provided,
        calculates the new balance and delta if necessary, and inserts a transaction record into the database.
        Args:
            user_id (int): The ID of the user for whom the transaction is being logged.
            user_is_postpaid (bool): True if the user is postpaid, False if prepaid.
            previous_money_cent (Optional[int], default=None): The user's previous balance in cents. If None, it is fetched from the database.
            new_money_cent (Optional[int], default=None): The user's new balance in cents. If None, it is calculated using delta_money_cent.
            delta_money_cent (Optional[int], default=None): The change in balance in cents. If None, it is calculated using new_money_cent.
            description (Optional[str], default=None): A description of the transaction.
        Raises:
            HTTPException: If the user is not found, if both new_money_cent and delta_money_cent are missing,
                           or if the transaction could not be logged.
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
        raise HTTPException(status_code=400, detail="Either new_money or delta_money must be provided, not both")
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

    print(f"set_postpaid_user_money: {user_id}, {money}")
    _log_transaction(user_id, user_is_postpaid=True, new_money_cent=money, description="Set money manually via Admin UI")
    t = text("UPDATE users_postpaid SET money = :money WHERE id = :id")
    with engine.connect() as connection:
        result = connection.execute(t, {"id": user_id, "money": money})
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        connection.commit()
    return result.rowcount

def drink_postpaid_user(user_id: int, drink_type: str = ""):
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
    prev_activated = get_postpaid_user(user_id)["activated"]
    t = text("UPDATE users_postpaid SET activated = :activated WHERE id = :id")
    with engine.connect() as connection:
        result = connection.execute(t, {"id": user_id, "activated": not prev_activated})
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        connection.commit()
    return result.rowcount


def get_prepaid_user(user_id: int):
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
    Retrieve a prepaid user from the database by their username.
    Args:
        username (str): The username of the user to retrieve.
    Returns:
        dict: A dictionary containing the user's id, username, money, activated status, and last_drink timestamp.
    Raises:
        HTTPException: If no user with the given username is found, raises a 404 HTTPException.
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
    prev_activated = get_prepaid_user(user_id)["activated"]
    t = text("UPDATE users_prepaid SET activated = :activated WHERE id = :id")
    with engine.connect() as connection:
        result = connection.execute(t, {"id": user_id, "activated": not prev_activated})
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        connection.commit()
    return result.rowcount

def set_prepaid_user_money(user_id: int, money: int, postpaid_user_id: int):
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
    t = text("DELETE FROM users_prepaid WHERE id = :id")
    with engine.connect() as connection:
        result = connection.execute(t, {"id": user_id})
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        connection.commit()
    return result.rowcount
