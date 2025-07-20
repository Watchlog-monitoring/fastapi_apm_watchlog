from setuptools import setup, find_packages

setup(
    name="fastapi-apm-watchlog",
    license="MIT",
    version="1.0.4",
    description="FastAPI instrumentation for Watchlog APM with JSON OTLP export",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Mohammadreza",
    author_email="mohammadnajm75@gmail.com",
    url="https://github.com/Watchlog-monitoring/fastapi_apm_watchlog",
    packages=find_packages(),
    install_requires=[
        "opentelemetry-api>=1.9.0",
        "opentelemetry-sdk>=1.9.0",
        "opentelemetry-exporter-otlp-proto-http>=1.9.0",
        "opentelemetry-instrumentation-fastapi>=0.34b0",
        "opentelemetry-instrumentation-requests>=0.34b0",
        "dnspython>=2.0.0"
    ],
    python_requires=">=3.7",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Framework :: FastAPI",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent"
    ],
)
