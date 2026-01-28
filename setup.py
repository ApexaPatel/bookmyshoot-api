from setuptools import setup, find_packages

setup(
    name="bookmyshoot",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        # Your dependencies here
        "fastapi>=0.68.0",
        "uvicorn>=0.15.0",
        "pymongo>=3.12.0",
        "python-dotenv>=0.19.0",
        "pydantic>=1.8.0",
        "python-jose[cryptography]>=3.3.0",
        "passlib[bcrypt]>=1.7.4",
    ],
)
