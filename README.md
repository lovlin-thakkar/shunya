## Generating api key to use CLI locally

### Option 1 — use uv run (recommended)        
```
cd zenerate/web-py/apps/api                                                                                                                                                   
uv run python manage.py generate_api_key
```                                                                                                                                      
                                                                                                                                                                            
### Option 2 — activate the project venv first
```
source /Users/lovlinthakkar/PycharmProjects/Shunya/zenerate/web-py/.venv/bin/activate                                                                                         
python manage.py generate_api_key       
```                                                                                                                                      

The root .venv at /Users/lovlinthakkar/PycharmProjects/Shunya/.venv (Python 3.14) doesn't have knox — that's only the CLI's venv. Knox lives in zenerate/web-py/.venv (the uv 
workspace venv, Python 3.13).