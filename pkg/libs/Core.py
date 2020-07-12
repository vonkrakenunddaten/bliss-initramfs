# Copyright (C) 2012-2020 Jonathan Vasquez <jon@xyinn.org>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import shutil
import re

from subprocess import call
from subprocess import check_output
from subprocess import CalledProcessError

import pkg.libs.Variables as var

from pkg.libs.Tools import Tools

from pkg.hooks.Base import Base
from pkg.hooks.Luks import Luks
from pkg.hooks.Zfs import Zfs
from pkg.hooks.Modules import Modules
from pkg.hooks.Firmware import Firmware


class Core:
    """Contains the core of the application"""

    # List of binaries (That will be 'ldd'ed later)
    _binset = set()

    # List of modules that will be compressed
    _modset = set()

    # Enable the 'base' hook since all initramfs will have this
    Base.Enable()

    # Modules will now always be enabled since all initramfs can have
    # the ability to have 0 or more modules.
    Modules.Enable()

    @classmethod
    def LoadSettings(cls):
        """Loads all of the settings from the json file into the Hooks."""

        # This approach was taken since it was the easiest / cleanest
        # implementation in terms of keeping the application references
        # mostly the same, but still being able to load the external info.
        settings = Tools.LoadSettings()

        # Base
        Base._files = settings["base"]["files"]
        Base._kmod_links = settings["base"]["kmodLinks"]
        Base._udev_provider = settings["base"]["udevProvider"]

        # The udev provider is also part of the base required files. However,
        # we are simplifying it to only one entry in the json so that if the
        # user's provider defers, they only need to change it in one place.
        Base.AddFile(Base.GetUdevProvider())

        # Modules

        # A list of kernel modules to include in the initramfs
        # Format: "module1", "module2", "module3", ...

        # Example: To enable built in encryption support, nvme, i915,
        # you would have the following modules in your settings.json:
        # ["dm-crypt", "nvme", "i915"]
        Modules._files = settings["modules"]["files"]

        # ZFS

        # Required Files
        Zfs._files = settings["zfs"]["files"]

        # Optional Files. Will not fail if we fail to copy them.
        Zfs._optional_files = settings["zfs"]["optionalFiles"]

        # Man Pages. Not used for actual initramfs environment
        # since the initramfs doesn't have the applications required to
        # display these man pages without increasing the size a lot. However,
        # these are used by the 'sysresccd-moddat' scripts to generate
        # the sysresccd + zfs isos.
        # Should we copy the man pages?
        Zfs._use_man = settings["zfs"]["useMan"]

        # Note: Portage allows one to change the compression type with
        # PORTAGE_COMPRESS. In this situation, these files will have
        # a different extension. The user should adjust these if needed.
        Zfs._man = settings["zfs"]["manFiles"]

        # LUKS

        # Should we embed our keyfile into the initramfs?
        Luks._use_keyfile = settings["luks"]["useKeyfile"]

        # Path to the keyfile you would like to embedded directly into the initramfs.
        # This should be a non-encrypted keyfile since it will be used to automate
        # the decryption of your / pool (when your /boot is also on /).
        Luks._keyfile_path = settings["luks"]["keyfilePath"]

        # Should we embed our LUKS header into the initramfs?
        Luks._use_detached_header = settings["luks"]["useDetachedHeader"]

        # Path to the LUKS header you would like to embedded directly into the initramfs.
        Luks._detached_header_path = settings["luks"]["detachedHeaderPath"]

        # The "/sbin/dmsetup" required binary is used for udev cookie release
        # when cryptsetup announces udev support and attempts to decrypt the
        # drive. Without this, the cryptsetup will lock up and stay at
        # "waiting for zero"
        Luks._files = settings["luks"]["files"]

        # Firmware

        # Copy firmware?
        Firmware._use = settings["firmware"]["use"]

        # If enabled, all the firmware in /lib/firmware will be copied into the initramfs.
        # If you know exactly what firmware files you want, definitely leave this at 0 so
        # to reduce the initramfs size.
        Firmware._copy_all = settings["firmware"]["copyAll"]

        # A list of firmware files to include in the initramfs
        Firmware._files = settings["firmware"]["files"]

        # A list of firmware directories to include in the initramfs
        Firmware._directories = settings["firmware"]["directories"]

        # Variables
        var.bin = settings["systemDirectory"]["bin"]
        var.sbin = settings["systemDirectory"]["sbin"]
        var.lib = settings["systemDirectory"]["lib"]
        var.lib64 = settings["systemDirectory"]["lib64"]
        var.etc = settings["systemDirectory"]["etc"]

        # Preliminary binaries needed for the success of creating the initrd
        # but that are not needed to be placed inside the initrd
        var.preliminaryBinaries = settings["preliminaryBuildBinaries"]

        var.modulesDirectory = settings["modulesDirectory"]
        var.firmwareDirectory = settings["firmwareDirectory"]
        var.initrdPrefix = settings["initrdPrefix"]
        var.udevConfigDirectory = settings["udevConfigDirectory"]
        var.udevLibDirectory = settings["udevLibDirectory"]
        var.modprobeDirectory = settings["modprobeDirectory"]

    @classmethod
    def PrintMenuAndGetDesiredFeatures(cls):
        """Prints the menu and accepts user features."""
        # If the user didn't pass their desired features through the command
        # line, then ask them which initramfs they would like to generate.
        if not var.features:
            print("Which initramfs features do you want? (Separated by a comma):")
            Tools.PrintFeatures()
            var.features = Tools.Question("Features [1]: ")

            if var.features:
                var.features = cls.ConvertNumberedFeaturesToNamedList(var.features)
            else:
                var.features = ["zfs"]

            Tools.NewLine()
        else:
            var.features = var.features.split(",")

        for feature in var.features:
            if feature == "zfs":
                Zfs.Enable()
                Modules.AddFile("zfs")
            elif feature == "luks":
                Luks.Enable()
            # Just a base initramfs with no additional stuff
            # This can be used with other options though
            # (i.e you have your rootfs directly on top of LUKS)
            elif feature == "basic":
                pass
            elif feature == "exit":
                Tools.Warn("Exiting.")
                quit(0)
            else:
                Tools.Warn("Invalid Option. Exiting.")
                quit(1)

    @classmethod
    def ConvertNumberedFeaturesToNamedList(cls, numbered_feature_list):
        """Returns the name equivalent list of a numbered list of features."""
        named_features = []

        try:
            for feature in numbered_feature_list.split(","):
                feature_as_string = Tools._features[int(feature)].lower()
                named_features.append(feature_as_string)
        except KeyError:
            named_features.clear()
            named_features.append("exit")

        return named_features

    @classmethod
    def CreateBaselayout(cls):
        """Creates the base directory structure."""
        Tools.Info("Creating temporary directory at " + var.temp + " ...")

        for dir in var.baselayout:
            call(["mkdir", "-p", dir])

    @classmethod
    def GetDesiredKernel(cls):
        """Ask the user if they want to use their current kernel, or another one."""
        if not var.kernel:
            current_kernel = check_output(
                ["uname", "-r"], universal_newlines=True
            ).strip()

            message = (
                "Do you want to use the current kernel: " + current_kernel + " [Y/n]: "
            )
            choice = Tools.Question(message)
            Tools.NewLine()

            if choice == "y" or choice == "Y" or not choice:
                var.kernel = current_kernel
            elif choice == "n" or choice == "N":
                var.kernel = Tools.Question("Please enter the kernel name: ")
                Tools.NewLine()

                if not var.kernel:
                    Tools.Fail("You didn't enter a kernel. Exiting...")
            else:
                Tools.Fail("Invalid Option. Exiting.")

        # Set modules path to correct location and sets kernel name for initramfs
        var.modules = var.modulesDirectory + "/" + var.kernel + "/"
        var.lmodules = var.temp + "/" + var.modules
        var.initrd = var.initrdPrefix + var.kernel

        # Check modules directory
        cls.VerifyModulesDirectory()

    @classmethod
    def VerifyModulesDirectory(cls):
        """Check to make sure the kernel modules directory exists."""
        if not os.path.exists(var.modules):
            Tools.Fail("The modules directory for " + var.modules + " doesn't exist!")

    @classmethod
    def VerifySupportedArchitecture(cls):
        """Checks to see that the architecture is supported."""
        if var.arch != "x86_64":
            Tools.Fail("Your architecture isn't supported. Exiting.")

    @classmethod
    def VerifyPreliminaryBinaries(cls):
        """Checks to see if the preliminary binaries exist."""
        Tools.Info("Checking preliminary binaries ...")

        # If the required binaries don't exist, then exit
        for binary in var.preliminaryBinaries:
            if not os.path.isfile(Tools.GetProgramPath(binary)):
                Tools.BinaryDoesntExist(binary)

    @classmethod
    def GenerateModprobeInfo(cls):
        """Generates the modprobe information."""
        Tools.Info("Generating modprobe information ...")

        # Copy modules.order and modules.builtin just so depmod doesn't spit out warnings. -_-
        Tools.Copy(var.modules + "/modules.order")
        Tools.Copy(var.modules + "/modules.builtin")

        result = call(["depmod", "-b", var.temp, var.kernel])

        if result != 0:
            Tools.Fail(
                "Depmod was unable to refresh the dependency information for your initramfs!"
            )

    @classmethod
    def CopyFirmware(cls):
        """Copies the firmware files/directories if necessary."""
        if Firmware.IsEnabled():
            Tools.Info("Copying firmware...")

            if os.path.isdir(var.firmwareDirectory):
                if Firmware.IsCopyAllEnabled():
                    shutil.copytree(
                        var.firmwareDirectory, var.temp + var.firmwareDirectory
                    )
                else:
                    # Copy the firmware files
                    if Firmware.GetFiles():
                        try:
                            for fw in Firmware.GetFiles():
                                Tools.Copy(fw, directoryPrefix=var.firmwareDirectory)
                        except FileNotFoundError:
                            Tools.Warn(
                                "An error occurred while copying the following firmware file: {}".format(
                                    fw
                                )
                            )

                    # Copy the firmware directories
                    if Firmware.GetDirectories():
                        try:
                            for fw in Firmware.GetDirectories():
                                sourceFirmwareDirectory = os.path.join(
                                    var.firmwareDirectory, fw
                                )
                                targetFirmwareDirectory = (
                                    var.temp + sourceFirmwareDirectory
                                )
                                shutil.copytree(
                                    sourceFirmwareDirectory, targetFirmwareDirectory
                                )
                        except FileNotFoundError:
                            Tools.Warn(
                                "An error occurred while copying the following directory: {}".format(
                                    fw
                                )
                            )

            else:
                Tools.Fail(
                    "The {} directory does not exist".format(var.firmwareDirectory)
                )

    @classmethod
    def CreateLinks(cls):
        """Create the required symlinks."""
        Tools.Info("Creating symlinks ...")

        # Needs to be from this directory so that the links are relative
        os.chdir(var.GetTempBinDir())

        # Create busybox links
        cmd = (
            "chroot "
            + var.temp
            + ' /bin/busybox sh -c "cd /bin && /bin/busybox --install -s ."'
        )
        callResult = call(cmd, shell=True)

        if callResult != 0:
            Tools.Fail("Unable to create busybox links via chroot!")

        # Create 'sh' symlink to 'bash'
        os.remove(var.temp + "/bin/sh")
        os.symlink("bash", "sh")

        # Switch to the kmod directory, delete the corresponding busybox
        # symlink and create the symlinks pointing to kmod
        if os.path.isfile(var.GetTempSbinDir() + "/kmod"):
            os.chdir(var.GetTempSbinDir())
        elif os.path.isfile(var.GetTempBinDir() + "/kmod"):
            os.chdir(var.GetTempBinDir())

        for link in Base.GetKmodLinks():
            os.remove(var.temp + "/bin/" + link)
            os.symlink("kmod", link)

    @classmethod
    def CreateLibraryLinks(cls):
        """Creates symlinks from library files found in each /usr/lib## dir to the /lib[32/64] directories."""
        if os.path.isdir(var.temp + "/usr/lib") and os.path.isdir(var.temp + "/lib64"):
            cls._FindAndCreateLinks("/usr/lib/", "/lib64")

        if os.path.isdir(var.temp + "/usr/lib32") and os.path.isdir(
            var.temp + "/lib32"
        ):
            cls._FindAndCreateLinks("/usr/lib32/", "/lib32")

        if os.path.isdir(var.temp + "/usr/lib64") and os.path.isdir(
            var.temp + "/lib64"
        ):
            cls._FindAndCreateLinks("/usr/lib64/", "/lib64")

        # Create links to libraries found within /lib itself
        if os.path.isdir(var.temp + "/lib") and os.path.isdir(var.temp + "/lib"):
            cls._FindAndCreateLinks("/lib/", "/lib")

    @classmethod
    def _FindAndCreateLinks(cls, sourceDirectory, targetDirectory):
        pcmd = (
            "find "
            + sourceDirectory
            + ' -iname "*.so.*" -exec ln -sf "{}" '
            + targetDirectory
            + " \;"
        )
        cmd = f'chroot {var.temp} /bin/busybox sh -c "{pcmd}"'
        call(cmd, shell=True)

        pcmd = (
            "find "
            + sourceDirectory
            + ' -iname "*.so" -exec ln -sf "{}" '
            + targetDirectory
            + " \;"
        )
        cmd = f'chroot {var.temp} /bin/busybox sh -c "{pcmd}"'
        call(cmd, shell=True)

    @classmethod
    def CopyUdevAndSupportFiles(cls):
        """Copies udev and files that udev uses, like /etc/udev/*, /lib/udev/*, etc."""
        # Copy all of the udev files
        udev_conf_dir = var.udevConfigDirectory
        temp_udev_conf_dir = var.temp + udev_conf_dir

        if os.path.isdir(udev_conf_dir):
            shutil.copytree(udev_conf_dir, temp_udev_conf_dir)

        udev_lib_dir = var.udevLibDirectory
        temp_udev_lib_dir = var.temp + udev_lib_dir

        if os.path.isdir(udev_lib_dir):
            shutil.copytree(udev_lib_dir, temp_udev_lib_dir)

        # Rename udevd and place in /sbin
        udev_provider = Base.GetUdevProvider()
        systemd_dir = os.path.dirname(udev_provider)

        sbin_udevd = var.sbin + "/udevd"
        udev_provider_temp = var.temp + udev_provider

        if os.path.isfile(udev_provider_temp) and udev_provider != sbin_udevd:
            udev_provider_new = var.temp + sbin_udevd
            os.rename(udev_provider_temp, udev_provider_new)

            temp_systemd_dir = var.temp + systemd_dir

            # If the directory is empty, than remove it.
            # With the recent gentoo systemd root prefix move, it is moving to
            # /lib/systemd. Thus this directory also contains systemd dependencies
            # such as: libsystemd-shared-###.so
            # https://gentoo.org/support/news-items/2017-07-16-systemd-rootprefix.html
            if not os.listdir(temp_systemd_dir):
                os.rmdir(temp_systemd_dir)

    @classmethod
    def DumpSystemKeymap(cls):
        """Dumps the current system's keymap."""
        pathToKeymap = var.temp + "/etc/keymap"
        result = call("dumpkeys > " + pathToKeymap, shell=True)

        if result != 0 or not os.path.isfile(pathToKeymap):
            Tools.Warn(
                "There was an error dumping the system's current keymap. Ignoring."
            )

    @classmethod
    def LastSteps(cls):
        """Performes any last minute steps like copying zfs.conf,
           giving init execute permissions, setting up symlinks, etc.
        """
        Tools.Info("Performing finishing steps ...")

        # Create mtab file
        call(["touch", var.temp + "/etc/mtab"])

        if not os.path.isfile(var.temp + "/etc/mtab"):
            Tools.Fail("Error creating the mtab file. Exiting.")

        cls.CreateLibraryLinks()

        # Copy the init script
        Tools.SafeCopy(var.files_dir + "/init", var.temp)

        # Give execute permissions to the script
        cr = call(["chmod", "u+x", var.temp + "/init"])

        if cr != 0:
            Tools.Fail("Failed to give executive privileges to " + var.temp + "/init")

        # Sets initramfs script version number
        cmd = f"echo {var.version} > {var.temp}/version.bliss"
        call(cmd, shell=True)

        # Copy all of the modprobe configurations
        if os.path.isdir(var.modprobeDirectory):
            shutil.copytree(var.modprobeDirectory, var.temp + var.modprobeDirectory)

        cls.CopyUdevAndSupportFiles()
        cls.DumpSystemKeymap()

        # Any last substitutions or additions/modifications should be done here

        if Luks.IsEnabled():
            # Copy over our keyfile if the user activated it
            if Luks.IsKeyfileEnabled():
                Tools.Flag("Embedding our keyfile into the initramfs...")
                Tools.SafeCopy(Luks.GetKeyfilePath(), var.temp + "/etc", "keyfile")

            # Copy over our detached header if the user activated it
            if Luks.IsDetachedHeaderEnabled():
                Tools.Flag("Embedding our detached header into the initramfs...")
                Tools.SafeCopy(
                    Luks.GetDetachedHeaderPath(), var.temp + "/etc", "header"
                )

        # Add any modules needed into the initramfs
        requiredModules = ",".join(Modules.GetFiles())
        cmd = f"echo {requiredModules} > {var.temp}/modules.bliss"
        call(cmd, shell=True)

        cls.CopyLibGccLibrary()

    @classmethod
    def CopyLibGccLibrary(cls):
        """Copy the 'libgcc' library so that when libpthreads loads it during runtime."""
        # https://github.com/zfsonlinux/zfs/issues/4749.

        # Find the correct path for libgcc
        libgccFilename = "libgcc_s.so"
        libgccFilenameMain = libgccFilename + ".1"

        # check for gcc-config
        gccConfigPath = Tools.GetProgramPath("gcc-config")

        if gccConfigPath:
            # Try gcc-config
            cmd = "gcc-config -L | cut -d ':' -f 1"
            res = Tools.Run(cmd)

            if res:
                # Use path from gcc-config
                libgccPath = res[0] + "/" + libgccFilenameMain
                Tools.SafeCopy(libgccPath, var.GetTempLib64Dir())
                os.chdir(var.GetTempLib64Dir())
                os.symlink(libgccFilenameMain, libgccFilename)
                return

        # Doing a 'whereis <name of libgcc library>' will not work because it seems
        # that it finds libraries in /lib, /lib64, /usr/lib, /usr/lib64, but not in
        # /usr/lib/gcc/ (x86_64-pc-linux-gnu/5.4.0, etc)

        # When a better approach is found, we can plug it in here directly and return
        # in the event that it succeeds. If it fails, we just continue execution
        # until the end of the function.

        # If we've reached this point, we have failed to copy the gcc library.
        Tools.Fail("Unable to retrieve the gcc library path!")

    @classmethod
    def CreateInitramfs(cls):
        """Create the initramfs."""
        Tools.Info("Creating the initramfs ...")

        # The find command must use the `find .` and not `find ${T}`
        # because if not, then the initramfs layout will be prefixed with
        # the ${T} path.
        os.chdir(var.temp)

        call(
            [
                "find . -print0 | cpio -o --null --format=newc | gzip -9 > "
                + var.home
                + "/"
                + var.initrd
            ],
            shell=True,
        )

        if not os.path.isfile(var.home + "/" + var.initrd):
            Tools.Fail("Error creating the initramfs. Exiting.")

    @classmethod
    def VerifyBinaries(cls):
        """Checks to see if the binaries exist, if not then emerge."""
        Tools.Info("Checking required files ...")

        # Check required base files
        cls.VerifyBinariesExist(Base.GetFiles())

        # Check required luks files
        if Luks.IsEnabled():
            Tools.Flag("Using LUKS")
            cls.VerifyBinariesExist(Luks.GetFiles())

        # Check required zfs files
        if Zfs.IsEnabled():
            Tools.Flag("Using ZFS")
            cls.VerifyBinariesExist(Zfs.GetFiles())

    @classmethod
    def VerifyBinariesExist(cls, vFiles):
        """Checks to see that all the binaries in the array exist and errors if they don't."""
        for file in vFiles:
            if not os.path.exists(file):
                Tools.BinaryDoesntExist(file)

    @classmethod
    def CopyBinaries(cls):
        """Copies the required files into the initramfs."""
        Tools.Info("Copying binaries ...")

        cls.FilterAndInstall(Base.GetFiles())

        if Luks.IsEnabled():
            cls.FilterAndInstall(Luks.GetFiles())

        if Zfs.IsEnabled():
            cls.FilterAndInstall(Zfs.GetFiles())
            cls.FilterAndInstall(Zfs.GetOptionalFiles(), dontFail=True)

    @classmethod
    def CopyManPages(cls):
        """Copies the man pages."""
        if Zfs.IsEnabled() and Zfs.IsManEnabled():
            Tools.Info("Copying man pages ...")
            cls.CopyMan(Zfs.GetManPages())

    @classmethod
    def CopyMan(cls, files):
        """Safely copies man pages if available. Will not fail."""

        # Depending the ZFS version that the user is running,
        # some manual pages that the initramfs wants to copy might not
        # have yet been written. Therefore, attempt to copy the man pages,
        # but if we are unable to copy, then just continue.
        for f in files:
            Tools.Copy(f, dontFail=True)

    @classmethod
    def FilterAndInstall(cls, vFiles, **optionalArgs):
        """Filters and installs each file in the array into the initramfs.

            Optional Args:
                dontFail - Same description as the one in Tools.Copy.
        """
        for file in vFiles:
            # If the application is a binary, add it to our binary set. If the application is not
            # a binary, then we will get a CalledProcessError because the output will be null.
            try:
                check_output(
                    "file -L " + file.strip() + ' | grep "linked"',
                    shell=True,
                    universal_newlines=True,
                ).strip()
                cls._binset.add(file)
            except CalledProcessError:
                pass

            # Copy the file into the initramfs
            Tools.Copy(file, dontFail=optionalArgs.get("dontFail", False))

    @classmethod
    def CopyModules(cls):
        """Copy modules and their dependencies."""
        moddeps = set()

        # Build the list of module dependencies
        Tools.Info("Copying modules ...")

        # Checks to see if all the modules in the list exist (if any)
        for file in Modules.GetFiles():
            try:
                cmd = (
                    "find "
                    + var.modules
                    + ' -iname "'
                    + file
                    + '.ko" | grep '
                    + file
                    + ".ko"
                )
                result = check_output(cmd, universal_newlines=True, shell=True).strip()
                cls._modset.add(result)
            except CalledProcessError:
                Tools.ModuleDoesntExist(file)

        # If a kernel has been set, try to update the module dependencies
        # database before searching it
        if var.kernel:
            try:
                result = call(["depmod", var.kernel])

                if result:
                    Tools.Fail("Error updating module dependency database!")
            except FileNotFoundError:
                # This should never occur because the application checks
                # that root is the user that is running the application.
                # Non-administraative users normally don't have access
                # to the 'depmod' command.
                Tools.Fail("The 'depmod' command wasn't found.")

        # Get the dependencies for all the modules in our set
        for file in cls._modset:
            # Get only the name of the module
            match = re.search("(?<=/)[a-zA-Z0-9_-]+.ko", file)

            if match:
                sFile = match.group().split(".")[0]

                cmd = (
                    "modprobe -S "
                    + var.kernel
                    + " --show-depends "
                    + sFile
                    + " | awk -F ' ' '{print $2}'"
                )
                results = check_output(cmd, shell=True, universal_newlines=True).strip()

                for i in results.split("\n"):
                    moddeps.add(i.strip())

        # Copy the modules/dependencies
        if moddeps:
            for module in moddeps:
                Tools.Copy(module)

            # Update module dependency database inside the initramfs
            cls.GenerateModprobeInfo()

    @classmethod
    def CopyDependencies(cls):
        """Gets the library dependencies for all our binaries and copies them into our initramfs."""
        Tools.Info("Copying library dependencies ...")

        bindeps = set()

        # Musl and non-musl systems are supported.
        possible_libc_paths = [
            var.lib64 + "/ld-linux-x86-64.so*",
            var.lib + "/ld-musl-x86_64.so*",
        ]
        libc_found = False

        for libc in possible_libc_paths:
            try:
                # (Dirty implementation) Use the exit code of grep with no messages being outputed to see if this interpreter exists.
                # We don't know the name yet which is why we are using the wildcard in the variable declaration.
                result = call("grep -Uqs thiswillnevermatch " + libc, shell=True)

                # 0 = match found
                # 1 = file exists but not found
                # 2 = file doesn't exist
                # In situations 0 or 1, we are good, since we just care that the file exists.
                if result != 0 and result != 1:
                    continue

                # Get the interpreter name that is on this system
                result = check_output(
                    "ls " + libc, shell=True, universal_newlines=True
                ).strip()

                # Add intepreter to deps since everything will depend on it
                bindeps.add(result)
                libc_found = True
            except Exception as e:
                pass

        if not libc_found:
            Tools.Fail("No libc interpreters were found!")

        # Get the dependencies for the binaries we've collected and add them to
        # our bindeps set. These will all be copied into the initramfs later.
        for binary in cls._binset:
            cmd = (
                "ldd "
                + binary
                + " | awk -F '=>' '{print $2}' | awk -F ' ' '{print $1}' | sed '/^ *$/d'"
            )
            results = check_output(cmd, shell=True, universal_newlines=True).strip()

            if results:
                for library in results.split("\n"):
                    bindeps.add(library)

        # Copy all the dependencies of the binary files into the initramfs
        for library in bindeps:
            Tools.Copy(library)
