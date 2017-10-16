def test():
    mock_function('foo.bar.some_function')
    mock_function("foo."
                  "bar.some_function")
    mock_function('foo.'
                  """bar."""
                  'some_function')
    mock_function('foo.'
                  'bar.'
                  'some_'
                  "function")
