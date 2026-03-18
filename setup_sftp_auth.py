"""core/_sftp_auth.py를 .so로 컴파일하는 빌드 스크립트."""
from Cython.Build import cythonize
from setuptools import setup, Extension

setup(
    ext_modules=cythonize(
        [Extension("core._sftp_auth", ["core/_sftp_auth.py"])],
        compiler_directives={"language_level": "3"},
    ),
)
