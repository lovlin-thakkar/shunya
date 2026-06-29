from setuptools import setup

setup(
    name="shunya-cli",
    version="0.1.0",
    packages=["cli"],
    package_dir={"cli": "."},
    install_requires=["httpx", "typer", "rich"],
    entry_points={
        "console_scripts": [
            "shunya=cli.main:main",
        ],
    },
)
