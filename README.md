# XML PyP

This is an XML Python processing instruction processor.
It executes Python code in XML processing instructions whose targets are "`py`"
and replaces the processing instruction tags with the printed contents by the code.

For example, the following XML code

```xml
<?xml version="1.0" ?>
<msg><?py print("Hello, world!", end="") ?></msg>
```

will be translated to

```xml
<?xml version="1.0" ?>
<msg>Hello, world!</msg>
```
