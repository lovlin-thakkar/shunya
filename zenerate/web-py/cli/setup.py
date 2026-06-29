from setuptools import setup, find_packages

setup(
    name="shunya-cli",
    version="0.1.0",
    packages=find_packages(where=".", include=["cli", "cli.*"]),
    package_dir={"": "."},
    install_requires=["httpx", "typer", "rich"],
    entry_points={
        "console_scripts": [
            "shunya=cli.main:main",
        ],
    },
)
