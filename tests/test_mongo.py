from datetime import datetime
from typing import List

import pytest
from bson.objectid import ObjectId
from pymongo import MongoClient
from pymongo.collection import ReturnDocument
from pymongo.command_cursor import CommandCursor
from pymongo.results import DeleteResult, UpdateResult

from monorm import Model, EmbeddedModel
from monorm.fields import ValidationError
from monorm.mongo import Cursor
from monorm.utils import random_lower_letters


class User(EmbeddedModel):
    first_name: str
    last_name: str


class Post(Model):
    user: User
    title: str
    content: str
    tags: List[str]
    visible: bool = True
    created_on: datetime = datetime.utcnow


@pytest.fixture
def db_populated(db):
    Post.set_db(db)
    for i in range(100):
        post = Post(
            user={'first_name': 'foo' + str(i), 'last_name': 'bar'},
            title=random_lower_letters(10),
            content=random_lower_letters(30),
        )
        post.save()
    return db


class TestSave:
    def test_save(self, db):
        Post.set_db(db)
        post = Post(
            user={'first_name': 'Foo', 'last_name': 'Bar'},
            title='hello world',
            content='wish world a better place',
            tags=['life', 'art']
        )
        assert post.pk is None
        post.save()
        pk = post.pk
        assert isinstance(pk, ObjectId)

    def test_save_after_modify(self, db):
        Post.set_db(db)
        post = Post(
            user={'first_name': 'Foo', 'last_name': 'Bar'},
            title='hello world',
            content='wish world a better place',
            tags=['life', 'art']
        )
        post.save()
        pk = post.pk
        post.title = 'hello earth'
        post.save()
        assert post.pk == pk

    def test_cannot_save_query_result(self, db_populated):
        Post.set_db(db_populated)
        post = Post.find_one()
        with pytest.raises(RuntimeError):
            post.save()


class TestIndexes:
    def test_basic_indexes(self, db):
        class MainModel(Model):
            class Meta:
                indexes = [
                    'a',
                    ('b', -1),
                    ['c', 'd'],
                    ['e', ('f', -1)],
                    [('h', 1), ('i', -1)]
                ]
        MainModel.set_db(db)
        coll = MainModel.get_collection()
        indexes = coll.index_information()
        assert 'a_1' in indexes
        assert 'b_-1' in indexes
        assert 'c_1_d_1' in indexes
        assert 'e_1_f_-1' in indexes
        assert 'h_1_i_-1' in indexes

    def test_indexes_with_options(self, db):
        class MainModel(Model):
            class Meta:
                indexes = [
                    {'key': 'a', 'name': 'foobar'},
                    {'key': ('b', -1), 'sparse': True},
                    {'key':  ['c', 'd'], 'unique': True},
                    {'key':  ['e', ('f', -1)], 'expire_after_seconds': 3600},
                    {'key': [('h', 1), ('i', -1)], 'expire_after_seconds': 3600, 'unique': True},
                ]
        MainModel.set_db(db)
        coll = MainModel.get_collection()
        indexes = coll.index_information()

        assert indexes['foobar']['key'] == [('a', 1)]
        assert indexes['b_-1']['sparse'] is True
        assert indexes['c_1_d_1']['unique'] is True
        assert indexes['e_1_f_-1']['expireAfterSeconds'] == 3600
        assert indexes['h_1_i_-1']['expireAfterSeconds'] == 3600 and indexes['h_1_i_-1']['unique'] is True

    def test_drop_indexes(self, db):
        db.get_collection('mainmodels').create_index('a')

        class MainModel(Model):
            class Meta:
                indexes = ['b']
        MainModel.set_db(db)
        coll = MainModel.get_collection()
        indexes = coll.index_information()

        assert 'a_1' not in indexes
        assert 'b_1' in indexes

    def test_modify_ttl_index(self, db):
        db.get_collection('mainmodels').create_index('expires_at', expireAfterSeconds=2400)

        class MainModel(Model):
            class Meta:
                indexes = [
                    {'key': 'expires_at', 'expire_after_seconds': 3600}
                ]
        MainModel.set_db(db)
        coll = MainModel.get_collection()
        indexes = coll.index_information()

        assert indexes['expires_at_1']['expireAfterSeconds'] == 3600

    def test_disable_auto_build_indexes(self, db):
        class MainModel(Model):
            class Meta:
                indexes = ['a']

        MainModel.set_db(db)
        MainModel.auto_build_index = False
        coll = MainModel.get_collection()
        indexes = coll.index_information()

        assert 'a_1' not in indexes


def test_set_db():
    class User(Model):
        greeting: str

    db = MongoClient().get_database('monorm-test1')
    User.set_db(db)

    assert User.get_db().name == 'monorm-test1'


def test_default_collection(db):
    class User(Model):
        greeting: str

    User.set_db(db)
    User.insert_one({'greeting': 'hello world'})
    assert User.get_collection().name == 'users'

    User.get_collection().drop()


def test_set_collection(db):
    class User(Model):
        greeting: str

    User.set_db(db)
    User.set_collection('members')
    User.insert_one({'greeting': 'hello world'})
    assert User.get_collection().name == 'members'

    User.get_collection().drop()


class TestInsert:
    def test_insert_one(self, db):
        Post.set_db(db)

        rv = Post.insert_one({
            'user': {'first_name': 'Foo', 'last_name': 'Bar'},
            'title': 'hello world',
            'content': 'wish world a better place',
            'tags': ['life', 'art']
        })
        assert isinstance(rv.inserted_id, ObjectId)

        with pytest.raises(ValidationError):
            Post.insert_one({'user': {'first_name': 42, 'last_name': 'Bar'}, 'title': 'hello world'})

    def test_insert_one_bypass_validation(self, db):
        Post.set_db(db)

        rv = Post.insert_one(
            {'user': {'first_name': 42, 'last_name': 'Bar'}, 'title': 'hello world'},
            bypass_document_validation=True
        )
        assert isinstance(rv.inserted_id, ObjectId)

    def test_insert_many(self, db):
        Post.set_db(db)

        rv = Post.insert_many([
            {'user': {'first_name': 'Foo', 'last_name': 'Bar'}, 'title': 'hello world'},
            {'user': {'first_name': 'Fox', 'last_name': 'Bax'}, 'title': 'hello earth'},
            {'user': {'first_name': 'Fax', 'last_name': 'Box'}, 'title': 'hello solar'},
        ])
        assert len(rv.inserted_ids) == 3

        with pytest.raises(ValidationError):
            Post.insert_many([
                {'user': {'first_name': 42, 'last_name': 'Bar'}, 'title': 'hello world'},
                {'user': {'first_name': 'Fox', 'last_name': 'Bax'}, 'title': 'hello earth'},
            ])
        with pytest.raises(ValidationError):
            Post.insert_many([
                {'user': {'first_name': 'Foo', 'last_name': 'Bar'}, 'title': 'hello world'},
                {'user': {'first_name': 42, 'last_name': 'Bax'}, 'title': 'hello earth'},
            ])

    def test_insert_many_bypass_validation(self, db):
        Post.set_db(db)

        rv = Post.insert_many([
            {'user': {'first_name': 'Foo', 'last_name': 'Bar'}, 'title': 'hello world'},
            {'user': {'first_name': 'Fox', 'last_name': 'Bax'}, 'title': 'hello earth'},
            {'user': {'first_name': 42, 'last_name': 'Box'}, 'title': 'hello solar'},
        ], bypass_document_validation=True)
        assert len(rv.inserted_ids) == 3


class TestQuery:
    def test_find_one(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.find_one()
        assert isinstance(rv, Post)
        assert isinstance(rv.user, User)
        assert len(rv.title) == 10

        rv = Post.find_one({'user.first_name': 'foo42'})
        assert rv is not None

    def test_find_one_without_result(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.find_one({'user.first_name': 'foo250'})
        assert rv is None

    def test_find(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.find()
        assert isinstance(rv, Cursor)
        assert isinstance(next(rv), Post)
        assert isinstance(next(rv).user, User)
        assert next(rv).user.last_name == 'bar'

        rv = Post.find({'user.last_name': 'bar'})
        assert isinstance(next(rv), Post)

    def test_find_without_result(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.find({'user.first_name': 'foo250'})
        assert isinstance(rv, Cursor)
        with pytest.raises(StopIteration):
            next(rv)

    def test_query_result_cannot_be_saved(self, db_populated):
        Post.set_db(db_populated)

        post = Post.find_one()
        with pytest.raises(RuntimeError):
            post.title = 'foobar'
            post.save()


class TestDelete:
    def test_delete_one(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.delete_one({})
        assert isinstance(rv, DeleteResult)

        rv = Post.delete_one({'user.first_name': 'foo42'})
        assert isinstance(rv, DeleteResult)

    def test_delete_one_not_existed(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.delete_one({'user.first_name': 'foo250'})
        assert isinstance(rv, DeleteResult)
        assert rv.deleted_count == 0

    def test_delete_many(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.delete_many({'user.first_name': 'foo42'})
        assert rv.deleted_count == 1

        rv = Post.delete_many({})
        assert rv.deleted_count == 99

    def test_delete_many_not_existed(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.delete_many({'user.first_name': 'foo250'})
        assert isinstance(rv, DeleteResult)
        assert rv.deleted_count == 0


class TestUpdate:
    def test_replace_one(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.replace_one(
            {'user.first_name': 'foo42'},
            {'user': {'first_name': 'foofoo', 'last_name': 'bar'}, 'title': 'hello world', 'content': '...'})
        assert isinstance(rv, UpdateResult)
        assert rv.modified_count == 1

    def test_replace_one_not_existed(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.replace_one(
            {'user.first_name': 'foo250'},
            {'user': {'first_name': 'foofoo', 'last_name': 'bar'}, 'title': 'hello world', 'content': '...'})
        assert isinstance(rv, UpdateResult)
        assert rv.modified_count == 0
        assert rv.upserted_id is None

    def test_replace_one_with_upsert(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.replace_one(
            {'user.first_name': 'foo250'},
            {'user': {'first_name': 'foofoo', 'last_name': 'bar'}, 'title': 'hello world', 'content': '...'},
            upsert=True
        )
        assert isinstance(rv, UpdateResult)
        assert rv.modified_count == 0
        assert rv.upserted_id is not None

    def test_replace_one_raise_validation_error(self, db_populated):
        Post.set_db(db_populated)

        with pytest.raises(ValidationError):
            Post.replace_one(
                {'user.first_name': 'foo250'},
                {'user': {'first_name': 42, 'last_name': 'bar'}, 'title': 'hello world', 'content': '...'},
                upsert=True
            )

    def test_replace_one_bypass_validation(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.replace_one(
            {'user.first_name': 'foo250'},
            {'user': {'first_name': 42, 'last_name': 'bar'}, 'title': 'hello world', 'content': '...'},
            upsert=True,
            bypass_document_validation=True
        )
        assert isinstance(rv, UpdateResult)

    def test_update_one(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.update_one({'user.first_name': 'foo42'}, {'$set': {'title': 'hello world'}})
        assert isinstance(rv, UpdateResult)

    def test_update_many(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.update_many({'user.last_name': 'bar'}, {'$set': {'title': 'hello world'}})
        assert isinstance(rv, UpdateResult)
        assert rv.modified_count == 100


class TestFindAndXXX:
    def test_find_one_and_delete(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.find_one_and_delete({'user.first_name': 'foo42'})
        assert isinstance(rv, Post)
        assert rv.user.last_name == 'bar'

        rv = Post.find_one_and_delete({'user.first_name': 'foo250'})
        assert rv is None

    def test_find_one_and_replace(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.find_one_and_replace(
            {'user.first_name': 'foo42'},
            {'user': {'first_name': 'foo420', 'last_name': 'bar'}, 'title': 'hello world', 'content': '...'},
        )
        assert isinstance(rv, Post)

    def test_find_one_and_replace_not_existed(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.find_one_and_replace(
            {'user.first_name': 'foo250'},
            {'user': {'first_name': 'foo420', 'last_name': 'bar'}, 'title': 'hello world', 'content': '...'},
        )
        assert rv is None

    def test_find_one_and_replace_with_upsert(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.find_one_and_replace(
            {'user.first_name': 'foo250'},
            {'user': {'first_name': 'foo420', 'last_name': 'bar'}, 'title': 'hello world', 'content': '...'},
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        assert isinstance(rv, Post)

    def test_find_one_and_replace_raise_validation_error(self, db_populated):
        Post.set_db(db_populated)

        with pytest.raises(ValidationError):
            Post.find_one_and_replace(
                {'user.first_name': 'foo42'},
                {'user': {'first_name': 13, 'last_name': 'bar'}, 'title': 'hello world', 'content': '...'},
            )

    def test_find_one_and_replace_bypass_validation(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.find_one_and_replace(
            {'user.first_name': 'foo13'},
            {'user': {'first_name': 13, 'last_name': 'bar'}, 'title': 'hello world', 'content': '...'},
            bypass_document_validation=True
        )
        assert isinstance(rv, Post)

    def test_find_one_and_update(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.find_one_and_update({'user.first_name': 'foo42'}, {'$set': {'user.first_name': 'foo420'}})
        assert isinstance(rv, Post)
        assert rv.user.last_name == 'bar'

        rv = Post.find_one_and_update({'user.first_name': 'foo250'}, {'$set': {'user.first_name': 'foo2500'}})
        assert rv is None


class TestAggregation:
    def test_aggregation(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.aggregate([
            {'$sort': {'title': 1}}
        ])
        assert isinstance(rv, CommandCursor)
        assert next(rv)['user']['last_name'] == 'bar'

    def test_estimated_document_count(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.estimated_document_count()
        assert rv <= 110

    def test_count_documents(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.count_documents({})
        assert rv == 100

    def test_distinct(self, db_populated):
        Post.set_db(db_populated)

        rv = Post.distinct(key='title')
        assert 80 < len(rv) <= 100

        rv = Post.distinct(key='user.last_name')
        assert len(rv) == 1


if __name__ == '__main__':
    pytest.main()