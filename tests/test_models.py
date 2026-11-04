import pytest
from sqlalchemy.exc import IntegrityError

from lilac_chatbot.extensions import db
from lilac_chatbot.models import ChatMessage, ChatThread, User, utcnow


def make_user(**kw):
    values = {
        "email": "a@example.test",
        "username": "alice",
        "first_name": "Alice",
        "last_name": "A",
        "password_hash": "x",
    }
    return User(**{**values, **kw})


def test_email_and_username_are_unique(app):
    with app.app_context():
        db.session.add(make_user())
        db.session.commit()
        db.session.add(make_user(username="other"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        db.session.add(make_user(email="other@example.test"))
        with pytest.raises(IntegrityError):
            db.session.commit()


def test_a_customer_has_one_conversation(app):
    with app.app_context():
        user = make_user()
        db.session.add(user)
        db.session.commit()
        db.session.add(ChatThread(user_id=user.id, conversation_id="conv_1"))
        db.session.commit()
        db.session.add(ChatThread(user_id=user.id, conversation_id="conv_2"))
        with pytest.raises(IntegrityError):
            db.session.commit()


def test_deleting_a_customer_deletes_their_conversation_and_messages(app):
    with app.app_context():
        user = make_user()
        user.thread = ChatThread(conversation_id="conv_1", messages=[ChatMessage(sender="user", text="hi")])
        db.session.add(user)
        db.session.commit()
        db.session.delete(user)
        db.session.commit()
        assert db.session.scalars(db.select(ChatMessage)).all() == []
        assert db.session.scalars(db.select(ChatThread)).all() == []


def test_messages_come_back_in_order(app):
    with app.app_context():
        user = make_user()
        user.thread = ChatThread(
            conversation_id="c", messages=[ChatMessage(sender="user", text=str(i)) for i in range(5)]
        )
        db.session.add(user)
        db.session.commit()
        assert [m.text for m in db.session.get(User, user.id).thread.messages] == list("01234")


def test_timestamps_are_naive_utc_without_the_deprecated_call():
    assert utcnow().tzinfo is None


def test_a_message_is_not_an_order_unless_flagged(app):
    with app.app_context():
        user = make_user()
        user.thread = ChatThread(conversation_id="c", messages=[ChatMessage(sender="user", text="hi")])
        db.session.add(user)
        db.session.commit()
        message = db.session.scalars(db.select(ChatMessage)).one()
        assert message.is_order is False and message.order_id is None
