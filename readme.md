# <img style="vertical-align: top;" src="https://github.com/cdhigh/weedata/blob/main/logo.png?raw=true" height="50px"> weedata

[![PyPI version shields.io](https://img.shields.io/pypi/v/weedata.svg)](https://pypi.python.org/pypi/weedata/) ![python](https://img.shields.io/badge/python-3.6+-blue) [![License: MIT](https://img.shields.io/badge/License-MIT%20-blue.svg)](https://github.com/cdhigh/weedata/blob/main/LICENSE)


The weedata is a python ODM/ORM module for Google Cloud Datastore / MongoDB / Redis, featuring a compatible interface with [Peewee](https://github.com/coleifer/peewee).    
The main priority of this library is to ensure compatibility with the Peewee API.    
If you don't use advanced SQL features such as multi-table join queries and more, you can easily switch between SQL and NoSQL without modifying your application code.    
I know using NoSQL as if it were SQL is not a very smart idea, but it can achieve maximum compatibility with various databases, so, just choose what you like.    



# Quickstart
Alright, if you're already familiar with Peewee, you basically don't need this documentation.     
The majority of the content in this document is directly taken from the [official Peewee documentation](http://docs.peewee-orm.com), with minimal alterations. Gratitude is expressed in advance for this.   

  >> If you have any questions during use, you can first check the peewee documentation, and then try in weedata to verify if weedata supports it or not.




## How to migrate your peewee-based project to NoSQL
Only Two Steps Needed:

1. Change 
```python
from peewee import *
```
to
```python
from weedata import *
```

2. Change
```python
db = SqliteDatabase(dbName)
```
to one of the following lines:
```python
db = DatastoreClient(project="AppId")
db = MongoDbClient(dbName, "mongodb://localhost:27017/")
db = RedisDbClient("AppId", "redis://127.0.0.1:6379/")
```



## Installation

weedata supports Google Cloud Datastore, MongoDB and Redis.    
To use Google Cloud Datastore, you need to install google-cloud-datastore [optional, only install if need].   
To use MongoDB, you need to install pymongo [optional, only install if need].   

To use redis, you need to install Redis-py [optional, only install if need].   

```bash
pip install google-cloud-datastore
pip install pymongo
pip install redis
pip install weedata
```


### DatastoreClient
To use Google Cloud Datastore, firstly you need to create a project, set up authentication. You can refer to [Firestore in Datastore mode documentation](https://cloud.google.com/datastore/docs) or [backDatastore mode client libraries](https://cloud.google.com/datastore/docs/reference/libraries) or [Python Client for Google Cloud Datastore API](https://cloud.google.com/python/docs/reference/datastore/latest) for guidance.
```python
API signature: DatastoreClient(project=None, namespace=None, credentials=None, \_http=None)
```

### MongoDbClient
weedata uses pymongo as the MongoDB driver. After correctly installing the MongoDB service and pymongo, create a client following this API signature.
The parameter 'project' corresponds to the MongoDB database name, and 'host' can be passed as complete database url.
```python
MongoDbClient(project, dbUrl='mongodb://127.0.0.1:27017/')
```

### RedisDbClient
weedata uses redis-py as the redis driver. After correctly installing the redis service and redis-py, create a client following this API signature.  
The parameter 'project' corresponds to the redis key prefix, and 'host' can be passed as complete database url, you can also choose which db to be used by passing the parameter 'db', the range is [0-15].
```python
RedisDbClient(project, dbUrl='redis://127.0.0.1:6379/0', key_sep=':')
```

> **Important Notice:**
> Redis functions as an in-memory database. Although it includes disk persistence capabilities, this feature does not ensure 100% data integrity and presents a potential risk of data loss. Prior to implementing Redis as a storage database, it is crucial to grasp pertinent knowledge and configure it appropriately, including enabling RDB (Redis Database) or AOF (Append Only File) functionality.
For example, you can add two lines in redis.conf:
```
appendonly yes
appendfsync always
or
appendonly yes
appendfsync everysec
```


### PickleDbClient
weedata also provides a simple database implementation PickleDbClient using Python's pickle library, which can be used for testing purposes and in applications with limited resources and low data integrity requirements.   
The parameter "dbName" is the filename of pickle file, if set to ":memory:", an in-memory database is created.  
```python
PickleDbClient(dbName, bakBeforeWrite=True)
```




## Model Definition

```python
from weedata import *

db = DatastoreClient(project="AppId")
db = MongoDbClient("AppId", "mongodb://localhost:27017/")
db = RedisDbClient("AppId")

class Person(Model):
    class Meta:
        database = db

    name = CharField()
    birthday = DateTimeField()
```

The best practice is to define a base class that connects to the database, and then have other models within your application inherit from it.

```python
class MyBaseModel(Model):
    class Meta:
        database = db

class Person(MyBaseModel):
    name = CharField()
    birthday = DateTimeField()

class Message(MyBaseModel):
    context = TextField()
    read_count = IntegerField(default=0)
```

Or you can setup or change database connection dynamically by using bind method.
```python
Person.bind(db)
Message.bind(db)

#or
db.bind([Person, Message])
```



## Storing data

Let's begin by populating the database with some people. We will use the save() and create() methods to add and update people's records.

```python
from datetime import datetime
uncle_bob = Person(name='Bob', birthday=datetime(1960, 1, 15))
uncle_bob.save()
```

You can also add a person by calling the create() method, which returns a model instance. The insert_many() function is a convenient method for adding many data at once:

```python
grandma = Person.create(name='grandma', birthday=datetime(1935, 3, 1))
Person.insert_many([{'name':'Herb', 'birthday':datetime(1950, 5, 5)}, {'name':'Adam', 'birthday':datetime(1990, 9, 1)}])
```



## Counting records

You can count the number of rows in any select query:

```python
Tweet.select().count()
Tweet.select().where(Tweet.id > 50).count()
```




## Updating data

To update data, modify the model instance and call save() to persist the changes.   
Here we will change Grandma's name and then save the changes in the database.    
Or you can use an update statement that supports all standard arithmetic operators:  

```python
grandma.name = 'Grandma'
grandma.save()

Person.update({Person.name: 'Grandma L.'}).where(Person.name == 'Grandma').execute() #Changing to other name
Person.update(name='Grandma').where(Person.name == 'Grandma').execute() #Changing to other name
Person.update({Person.name: 'Dear. ' + Person.name}).where(Person.birthday > datetime(1950, 5, 5)).execute() #Adding a title of respect before someone's name
# update statement supports: +, -, *, /, //, %, **, <<, >>, &, |, ^
```

To delete one or many instances from database:

```python
herb.delete_instance()
Person.delete().where(Person.birthday < datetime(1950, 5, 4)).execute()
```

To remove the whole collection(MongoDb)/kind(datastore), you can use:

```python
Person.drop_table()
db.drop_tables([Person, Message])
```


## Retrieving Data


### Getting single records
Let's retrieve Grandma's record from the database. To get a single record from the database, use Select.get():

```python
grandma = Person.get(name = 'Grandma')
grandma = Person.get(Person.name == 'Grandma')
grandma = Person.select().where(Person.name != 'Grandma').get()
grandma = Person.select().where(Person.name == 'Grandma').first()
grandma = Person.get_or_none(Person.name == 'Grandma')
grandma = Person.get_by_id('65bda09d6efd9b1130ffccb0')
grandma = Person.select().where(Person.id == '65bda09d6efd9b1130ffccb0').first()
```

```python
grandma = Person.select(Person.name, Person.birthday).where(Person.name == 'Grandma').first()
```

The code lines above return an instance of the Model. If, in some situations, you need a dictionary, you can use dicts() to return a standard Python dictionary.

```python
grandma.dicts()
grandma.dicts(only=[Person.name, Person.birthday])
grandma.dicts(exclude=[Person.birthday])
grandma.dicts(remove_id=True)
```



### Lists of records
Let's list all the people in the database:

```python
for person in Person.select():
    print(person.name)
```



### Sorting
Let's make sure these are sorted alphabetically by adding an order_by() clause:

```python
for person in Person.select().where(Person.birthday <= datetime(1960, 1, 15)).order_by(Person.name):
    print(person.name)

for person in Person.select().order_by(Person.birthday.desc()):
    print(person.name, person.birthday)
```



### Combining filter expressions

People whose birthday is between 1940 and 1960 (inclusive of both years):

```python
d1940 = datetime(1940, 1, 1)
d1960 = datetime(1960, 12, 31)
query = Person.select().where((Person.birthday >= d1940) & (Person.birthday <= d1960))
for person in query:
    print(person.name, person.birthday)


query = Person.select().where(Person.birthday.between(d1940, d1960))
query = Person.select().where(Person.birthday >= d1940).where(Person.birthday <= d1960)
query = Person.select().where((Person.birthday < d1940) | (Person.birthday > d1960))
query = Person.select().where(~((Person.birthday < d1940) | (Person.birthday > d1960)))
```


# Models and Fields

## Field types supported:
* BooleanField
* IntegerField
* BigIntegerField
* SmallIntegerField
* FloatField
* DoubleField
* DecimalField
* CharField
* FixedCharField
* TextField
* BlobField
* UUIDField
* DateTimeField
* JSONField
* ForeignKeyField
* PrimaryKeyField


## Reserved field names
The following names of fields reserved by the model, should be avoided for your fields:   

```_key, _id, id```


## Field initialization arguments
Parameters accepted by all field types and their default values:
* `unique = False` – create a unique index on this column.
* `index = None` – create an index on this column. If you want to store content longer than 1500 bytes in the datastore, set the index to False.   
* `default = None` – any value or callable to use as a default for uninitialized models
* `enforce_type = False` – determine if the new value is of a specific type.

Other parameters accepted by Peewee can be passed, weedata simply ignores them in a straightforward manner.



## Default field values
weedata can provide default values for fields when objects are created. For example to have an IntegerField default to zero rather than None, you could declare the field with a default value:

```python
class Message(Model):
    context = TextField()
    read_count = IntegerField(default=0)
```

In some instances it may make sense for the default value to be dynamic. A common scenario is using the current date and time. weedata allows you to specify a function in these cases, whose return value will be used when the object is created. Note we only provide the function, we do not actually call it:

```python
class Message(Model):
    context = TextField()
    timestamp = DateTimeField(default=datetime.datetime.now)
```


## Model options and table metadata
In order not to pollute the model namespace, model-specific configuration is placed in a special class called Meta (a convention borrowed from the django framework):

```python
db = MongoDbClient("AppId", "mongodb://localhost:27017/")

class Person(Model):
    name = CharField()
    birthday = DateTimeField()

    class Meta:
        database = db
```

Once the class is defined, you should not access ModelClass.Meta, but instead use ModelClass.\_meta.  
The ModelOptions class implements several methods which may be of use for retrieving model metadata.  

```python
Person._meta.fields
Person._meta.client
```
Now, the ModelOptions accepts two parameters:
* **database**: Indicating the backend database client instance to be used, if not set, you can call `Model.bind()` or `db.bind() ` at run time.
* **primary_key**: Optional, the name of the primary key at the underlying level of each database is different. It's called "key" in Datastore, for MongoDB, it's "\_id", to ensure compatibility with SQL and simplify application code, weedata automatically adds a primary key named 'id' with a string type. This primary key is only an application-level attribute variable and will not be saved to the underlying database.
If this name conflicts with your application, you can use the "primary_key" attribute to modify it, for example:

```python
class Meta
    database = db
    primary_key = 'id_'
```


# Querying

## Selecting a single record

```python
User.get_by_id('65bda09d6efd9b1130ffccb0')
User.get(User.username == 'Charlie')
User.get(username='Charlie')
User.select().where(User.username.in_(['Charlie', 'Adam'])).order_by(User.birthday.desc()).get()
```


## Filtering records
You can filter for particular records using normal python operators. weedata supports a wide variety of query operators.


### Query operators
The following types of comparisons are supported by weedata:

| Comparison          | Meaning                         |
|---------------------|---------------------------------|
| ==                  | x equals y                      |
| !=                  | x is not equal to y             |
| <                   | x is less than y                |
| <=                  | x is less than or equal to y    |
| >                   | x is greater than y             |
| >=                  | x is greater than or equal to y |
| .in_(list)          | IN lookup                       |
| .not_in(list)       | NOT IN lookup.                  |
| .between(v1, v2)    | Between lookup                  |
| .startswith(prefix) | lookup using a string prefix    |
| &                   | logical AND                     |
| \|                  | logical OR                      |
| ~                   | logical NOT (mongodb only)      |




## Some extra examples

```python
user = User.select().where(User.name == 'python').get()
user = User.select().where(User.name == 'python').first()
user = User.select().where(User.name.in_(['python', 'cobra'])).first()
user = User.select().where(User.name.not_in(['python', 'cobra'])).first()
users = User.select(User.name, User.score).where(User.name == 'python').execute()
users = User.select().where(User.birthdate.between(datetime.datetime(2024,1,1), datetime.datetime(2024,2,1))).execute()
user = User.select().where((User.name != 'python') & (User.name != 'cobra')).first()
user = User.select().where(User.name != 'python').where(User.name != 'cobra').first()
users = User.select().order_by(User.birthdate.desc(), User.score).limit(10).execute()
users = User.select().where((User.name == 'python') | (User.name == 'cobra')).execute()
users = list(User.get(User.age > 30))
Tweet.select().where(Tweet.content.startswith('de'))

User.update({User.score: User.att_days + (User.evaluation * 2)}).where(User.age < 10).execute()

User.replace(name='python', score=100, birthdate=datetime.datetime(2024,1,1)).execute()

```


# Changelog  
* v0.2.7
1. bugfix: fix query.dicts function


* v0.2.6
1. bugfix: Compatible with peewee, store datetime without timezone info.


* v0.2.5
1. bugfix: The compatibility problem of get_or_none().


* v0.2.4
1. Optimize the modification logic for JSONField, saving to the database at any time.    


* v0.2.3
1. bugfix: TextField/BlobField/JSONField initial params not worked.   


* v0.2.2
1. Delays connecting to the pymongo database until the first operation.   
2. The default Index property of TextField/BlobField/JSONField is set to False.   


* v0.2.1
1. Set index=False will exclude the field from indexes in datastore
2. Bugfix: datastore update query removes the fields unmodified


* v0.2.0
1. Supports Redis
2. Add a simple database implementation PickleDbClient
3. Supports ForeignKeyField
4. Add Model.replace() and Model.get_or_create() method
5. Add Field.startswith() query
6. [MongoDB/Redis] Auto create index when field with attr index=True or unique=True
7. Fix DoesNotExist not found error


* v0.1.0
Initial version

