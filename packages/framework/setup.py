"""The bundled ctypes engine is a Linux x86-64 asset, not a CPython extension."""
from setuptools import Distribution, setup
from setuptools.command.bdist_wheel import bdist_wheel


class NativeAssetDistribution(Distribution):
    def has_ext_modules(self):
        # Install into platlib even though ctypes loads the prebuilt asset.
        return True


class PlatformWheel(bdist_wheel):
    def finalize_options(self):
        super().finalize_options()
        self.root_is_pure = False

    def get_tag(self):
        return "py3", "none", "linux_x86_64"


setup(distclass=NativeAssetDistribution, cmdclass={"bdist_wheel": PlatformWheel})
