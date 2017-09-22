import functools
import memcache

client = memcache.Client(['127.0.0.1:11211'], debug=0)


def cached(time=1200):
  """
  Decorator that caches the result of a method for the specified time in seconds.

  Use it as:

    @cached(time=1200)
    def functionToCache(arguments):
      ...

  """
  def decorator(function):

    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        key = '%s%s%s' % (function.__name__, str(args), str(kwargs))
        value = client.get(key)
        if not value:
            value = function(*args, **kwargs)
            client.set(key, value, time=time)
        return value
    return wrapper

  return decorator