# <img style="vertical-align: top;" src="https://github.com/cdhigh/weedata/blob/main/logo.png?raw=true" height="50px"> weedata

[![PyPI version shields.io](https://img.shields.io/pypi/v/weedata.svg)](https://pypi.python.org/pypi/weedata/) ![python](https://img.shields.io/badge/python-3.6+-blue) [![License: MIT](https://img.shields.io/badge/License-MIT%20-blue.svg)](https://github.com/cdhigh/weedata/blob/main/LICENSE)


The weedata is a python ODM/ORM module for Google Cloud Datastore and MongoDB, featuring a compatible interface with [Peewee](https://github.com/coleifer/peewee).    
It has limited features, with a primary focus on compatibility with the Peewee API.    
If you don't use advanced SQL features such as foreign keys or multi-table join queries and more, you can easily switch between SQL and NoSQL without modifying your application code.    
I know using NoSQL as if it were SQL is not a very smart idea, but it can achieve maximum compatibility with various databases, so, just choose what you like.    



# Quickstart
Alright, if you're already familiar with Peewee, you basically don't need this documentation.     
The majority of the content in this document is directly taken from the [official Peewee documentation](http://docs.peewee-orm.com), with minimal alterations. Gratitude is expressed in advance for this.   

  >> If you have any questions during use, you can first check the peewee documentation, and then try in weedata to verify if weedata supports it or not.




## How to migrate your peewee-based project to NoSQL
Only Two Steps Needed:
1. Change 
```
from peewee import *
```
to
```
from weedata import *
```

2. Change
```
db = SqliteDatabase(dbName)
```
to one of the following lines:
```
db = DatastoreClient(project="project id")
db = MongoDbClient(dbName, "mongodb://localhost:27017/")
```



## Installation
weedata supports Google Cloud Datastore and MongoDB.    
To use Google Cloud Datastore, you need to install google-cloud-datastore [optional, only install if need].   
To use MongoDB, you need to install pymongo [optional, only install if need].   

```
pip install google-cloud-datastore
pip install pymongo
pip install weedata
```


### DatastoreClient
To use Google Cloud Datastore, firstly you need to create a project, set up authentication. You can refer to [Firestore in Datastore mode documentation](https://cloud.google.com/datastore/docs) or [backDatastore mode client libraries](https://cloud.google.com/datastore/docs/reference/libraries) or [Python Client for Google Cloud Datastore API](https://cloud.google.com/python/docs/reference/datastore/latest) for guidance.
```
API signature: DatastoreClient(project=None, namespace=None, credentials=None, \_http=None)
```

### MongoDbClient
weedata uses pymongo as the underlying MongoDB driver. After correctly installing the MongoDB service and pymongo, create a client following this API signature.
The parameter 'project' corresponds to the MongoDB database name, and 'host' can be passed as complete database url.
```
MongoDbClient(project, host=None, port=None, username=None, password=None)
```

## Model Definition

```
from weedata import *

db = DatastoreClient(project="project id")
db = MongoDbClient("project id", "mongodb://localhost:27017/")

class Person(Model):
    class Meta:
        database = db

    name = CharField()
    birthday = DateField()
```

The best practice is to define a base class that connects to the database, and then have other models within your application inherit from it.

```
class MyBaseModel(Model):
    class Meta:
        database = db

class Person(MyBaseModel):
    name = CharField()
    birthday = DateField()

class Message(MyBaseModel):
    context = TextField()
    read_count = IntegerField(default=0)
```



## Storing data
Let's begin by populating the database with some people. We will use the save() and create() methods to add and update people's records.

```
from datetime import date
uncle_bob = Person(name='Bob', birthday=date(1960, 1, 15))
uncle_bob.save()
```

You can also add a person by calling the create() method, which returns a model instance. The insert_many() function is a convenient method for adding many data at once:

```
grandma = Person.create(name='Grandma', birthday=date(1935, 3, 1))
Person.insert_many([{'name':'Herb', 'birthday':date(1950, 5, 5)}, {'name':'Adam', 'birthday':date(1990, 9, 1)}])
```

## Counting records
You can count the number of rows in any select query:

```
Tweet.select().count()
Tweet.select().where(Tweet.id > 50).count()
```

## Updating data
To update data, modify the model instance and call save() to persist the changes.   
Here we will change Grandma's name and then save the changes in the database.    
Or you can use an update statement that supports all standard arithmetic operators:  

```
grandma.name = 'Grandma L.'
grandma.save()  # Update grandma's name in the database.

Person.update({Person.name: 'Grandma L.'}).where(Person.name == 'Grandma').execute() #Changing to other name
Person.update({Person.name: 'Dear. ' + Person.name}).where(Person.birthday > date(1950, 5, 5)).execute() #Adding a title of respect before someone's name
# update statement supports: +, -, *, /, //, %, **, <<, >>, &, |, ^
```

To delete one or many instances from database:

```
herb.delete_instance()
Person.delete().where(Person.birthday < date(1950, 5, 4)).execute()
```

To remove the whole collection(MongoDb)/kind(datastore), you can use:

```
Person.drop_table()
db.drop_tables([Person, Message])
```

## Retrieving Data

### Getting single records
Let's retrieve Grandma's record from the database. To get a single record from the database, use Select.get():

```
grandma = Person.get(Person.name == 'Grandma L.')
grandma = Person.select().where(Person.name == 'Grandma L.').get()
grandma = Person.select().where(Person.name == 'Grandma L.').first()
grandma = Person.select().where(Person.name == 'Grandma L.').get_or_none()
grandma = Person.get_by_id('65bda09d6efd9b1130ffccb0')
grandma = Person.select().where(Person.id == '65bda09d6efd9b1130ffccb0').first()
```

```
grandma = Person.select(Person.name, Person.birthday).where(Person.name == 'Grandma L.').first()
```

The code lines above return an instance of the Model. If, in some situations, you need a dictionary, you can use dicts() to return a standard Python dictionary.

```
grandma.dicts()
grandma.dicts(only=[Person.name, Person.birthday])
grandma.dicts(exclude=[Person.birthday])
grandma.dicts(remove_id=True)
```



### Lists of records
Let's list all the people in the database:

```
for person in Person.select():
    print(person.name)

for person in Person.select().where(Person.birthday <= date(1960, 1, 15)):
    print(person.name)
```



### Sorting
Let's make sure these are sorted alphabetically by adding an order_by() clause:

```
for person in Person.select().where(Person.birthday <= date(1960, 1, 15)).order_by(Person.name):
    print(person.name)

for person in Person.select().order_by(Person.birthday.desc()):
    print(person.name, person.birthday)
```



### Combining filter expressions

People whose birthday is between 1940 and 1960 (inclusive of both years):

```
d1940 = date(1940, 1, 1)
d1960 = date(1960, 1, 1)
query = Person.select().where((Person.birthday > d1940) & (Person.birthday < d1960))
for person in query:
    print(person.name, person.birthday)

#alternative methods
query = Person.select().where(Person.birthday.between(d1940, d1960))
query = Person.select().where(Person.birthday > d1940).where(Person.birthday < d1960)
query = Person.select().where((Person.birthday < d1940) | (Person.birthday > d1960))
query = Person.select().where(~((Person.birthday < d1940) | (Person.birthday > d1960)))
```


# Models and Fields

## Field types supported:
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
* JSONField


## Reserved field names
The following names of fields reserved by the model, should be avoided for your fields:   

```_key, _id, id```

## Field initialization arguments
Parameters accepted by all field types and their default values:
* `default = None` – any value or callable to use as a default for uninitialized models
* `enforce_type = False` – determine if the new value is of a specific type.

Other parameters accepted by Peewee can be passed, weedata simply ignores them in a straightforward manner.



## Default field values
weedata can provide default values for fields when objects are created. For example to have an IntegerField default to zero rather than NULL, you could declare the field with a default value:

```
class Message(Model):
    context = TextField()
    read_count = IntegerField(default=0)
```

In some instances it may make sense for the default value to be dynamic. A common scenario is using the current date and time. weedata allows you to specify a function in these cases, whose return value will be used when the object is created. Note we only provide the function, we do not actually call it:

```
class Message(Model):
    context = TextField()
    timestamp = DateTimeField(default=datetime.datetime.now)
```

Note:
If you are using a field that accepts a mutable type (list, dict, etc), and would like to provide a default, it is a good idea to wrap your default value in a simple function so that multiple model instances are not sharing a reference to the same underlying object:

```
def house_defaults():
    return {'beds': 0, 'baths': 0}

class House(Model):
    number = TextField()
    street = TextField()
    attributes = JSONField(default=house_defaults)
```



## Creating a custom field
It is easy to add support for custom field types in weedata. In this example we will create a StringyBooleanField.

```
class StringyBooleanField(Field):
    def db_value(self, value): #The return value will be stored in database
        return "True" if value else "False"

    def python_value(self, value): #The return value will be used in python app code
        return value == "True"
```



## Model options and table metadata
In order not to pollute the model namespace, model-specific configuration is placed in a special class called Meta (a convention borrowed from the django framework):

```
db = MongoDbClient("project id", "mongodb://localhost:27017/")

class Person(Model):
    name = CharField()
    birthday = DateField()

    class Meta:
        database = db
```

Once the class is defined, you should not access ModelClass.Meta, but instead use ModelClass.\_meta:

```
Person.Meta
Traceback (most recent call last):
  File "<stdin>", line 1, in <module>
AttributeError: type object 'Person' has no attribute 'Meta'

Person._meta
<weedata.ModelOptions object at 0x7f51a2f03790>
```

The ModelOptions class implements several methods which may be of use for retrieving model metadata.

```
Person._meta.fields
Person._meta.client
```
Now, the ModelOptions accepts two parameters:
* database: Indicating the backend database client instance to be used, if not set, you can call `Model.bind()` at run time.
* primary_key: Optional, the name of the primary key at the underlying level of each database is different. For Datastore, it's called "key", for MongoDB, it's "\_id", To ensure compatibility with SQL and simplify application code, weedata automatically adds a primary key named 'id' with a string type. This primary key is only an application-level attribute variable and will not be saved to the underlying database.
If this name conflicts with your application, you can use the "primary_key" attribute to modify it, for example:

```
class Meta
    database = db
    primary_key = 'id_'
```


# Querying

## Selecting a single record

```
User.get_by_id('65bda09d6efd9b1130ffccb0')
User.get(User.username == 'Charlie')
User.select().where(User.username.in_(['Charlie', 'Adam'])).order_by(User.birthday.desc()).get()
```


## Filtering records
You can filter for particular records using normal python operators. weedata supports a wide variety of query operators.

### Query operators
The following types of comparisons are supported by weedata:

| Comparison     | Meaning                         |
|----------------|---------------------------------|
| ==             | x equals y                      |
| <              | x is less than y                |
| <=             | x is less than or equal to y    |
| >              | x is greater than y             |
| >=             | x is greater than or equal to y |
| !=             | x is not equal to y             |
| .in_(list)     | IN lookup                       |
| .not_in(list)  | NOT IN lookup.                  |
| &              | logical AND                     |
| \|             | logical OR                      |
| ~              | logical NOT (mongodb only)      |




### Some extra examples

```
user = User.select().where(User.name == 'python').get()
user = User.select().where(User.name == 'python').first()
user = User.select().where(User.name.in_(['python', 'cobra'])).first()
user = User.select().where(User.name.not_in(['python', 'cobra'])).first()
users = User.select(User.name, User.score).where(User.name == 'python').execute()
users = User.select().where(User.birthdate.between(datetime.datetime(2024,1,1), datetime.datetime(2024,2,1))).execute()
user = User.select().where((User.name != 'python') & (User.name != 'cobra')).first()
user = User.select().where(User.name != 'python').where(User.name != 'cobra').first()
user = User.select().order_by(User.birthdate.desc(), User.score).limit(10).execute()
user = User.select().where((User.name == 'python') | (User.name == 'cobra'))

User.update({User.score: User.att_days + (User.evaluation * 2)}).where(User.age < 10).execute()

```


# Changelog  

* v0.1.0
Initial version


