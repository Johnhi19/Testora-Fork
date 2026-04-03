import os
import docker
import tarfile
import tempfile
from os.path import join
from os import chdir, getcwd


class DockerExecutor:
    def __init__(self, container_name, project_name, coverage_files):
        client = docker.from_env()
        self.container = client.containers.get(container_name)
        self.container.start()

        # adapt paths of coverage files to the container's file system
        self.coverage_files = [f"/home/{project_name}/{f}" for f in coverage_files]

    def copy_code_to_container(self, code, target_file_path):
        target_dir = target_file_path.rsplit("/", 1)[0]
        target_file_name = target_file_path.rsplit("/", 1)[1]

        with tempfile.TemporaryDirectory() as tmp_dir:
            code_file = join(tmp_dir, target_file_name)
            with open(code_file, "w") as f:
                f.write(code)
            tar_file = join(tmp_dir, "archive.tar")
            with tarfile.open(tar_file, mode="w") as tar:
                wd = getcwd()
                try:
                    chdir(tmp_dir)
                    tar.add(target_file_name)
                finally:
                    chdir(wd)

            data = open(tar_file, "rb").read()
            self.container.put_archive(target_dir, data)

    def copy_file_from_container(self, file_path_in_container, target_dir):
        data, _ = self.container.get_archive(file_path_in_container)
        temp_tar_file = "temp.tar"
        with open(temp_tar_file, "wb") as f:
            for d in data:
                f.write(d)
        
        with tarfile.open(temp_tar_file, mode="r") as tar:
            tar.extractall(target_dir)

        os.remove(temp_tar_file)

    def execute_python_code(self, code):
        # create a fresh directory to get rid of any old state
        self.container.exec_run("rm -rf /tmp/Testora")
        self.container.exec_run("mkdir /tmp/Testora")

        self.copy_code_to_container(code, "/tmp/Testora/Testora_test_code.py")
        coverage_files = ",".join(f"\"{f}\"" for f in self.coverage_files)
        # -u to avoid non-deterministic buffering
        command = (
            f"timeout 300s python -u -m coverage run "
            f"--include={coverage_files} "
            f"--data-file /tmp/coverage_report /tmp/Testora/Testora_test_code.py"
        )

        # for scipy and numpy, make sure we run inside the their dev environment
        if self.container.name.startswith("scipy-dev"):
            command = (
                f"bash -c 'source /root/conda/etc/profile.d/conda.sh"
                f" && eval \"$(mamba shell hook --shell bash)\" && mamba activate scipy-dev"
                f" && {command}'"
            )
        elif self.container.name.startswith("numpy-dev"):
            command = (
                f"bash -c 'source /root/conda/etc/profile.d/conda.sh"
                f" && source /root/conda/etc/profile.d/mamba.sh"
                f"' && mamba activate numpy-dev && {command}'"
            )

        exec_result = self.container.exec_run(command)
        output = exec_result.output.decode("utf-8")

        self.copy_file_from_container(
            "/tmp/coverage_report", ".")
        with open("coverage_report", "rb") as f:
            coverage_report = f.read()

            return output, coverage_report

    def execute_shell(self, command):
        """Executes a shell command inside the container's dev environment."""
        
        # Wrap the command in the appropriate conda/mamba environment logic
        # logic copied from your execute_python_code method for consistency
        if self.container.name.startswith("scipy-dev"):
            command = (
                f"bash -c 'source /root/conda/etc/profile.d/conda.sh "
                f"&& eval \"$(mamba shell hook --shell bash)\" && mamba activate scipy-dev "
                f"&& cd /home/scipy "
                f"&& {command}'"
            )
        elif self.container.name.startswith("numpy-dev"):
            command = (
                f"bash -c 'source /root/conda/etc/profile.d/conda.sh "
                f"&& source /root/conda/etc/profile.d/mamba.sh "
                f"&& mamba activate numpy-dev && {command}'"
            )

        exec_result = self.container.exec_run(command)
        return exec_result.output.decode("utf-8"), exec_result.exit_code

if __name__ == "__main__":
    executor = DockerExecutor("scipy-dev3", "scipy", coverage_files=[])

    print("--- Locating the source file ---")
    find_out, _ = executor.execute_shell("find /home/scipy -name _fmm_core.cpp")
    target_file = find_out.strip()

    if target_file:
        print(f"--- Found file at: {target_file} ---")
        
        # PATCH VIA PYTHON INSTEAD OF SED
        # This is way safer than dealing with shell escaping
        patch_python_code = f"""
with open('{target_file}', 'r') as f:
    content = f.read()
if '#include <cstdint>' not in content:
    with open('{target_file}', 'w') as f:
        f.write('#include <cstdint>\\n' + content)
print('Successfully patched {target_file}')
"""
        print("--- Applying Patch via Python ---")
        # Use your existing execute_python_code method!
        patch_output, _ = executor.execute_python_code(patch_python_code)
        print(patch_output)

        # NOW RUN THE BUILD
        print("--- Starting Build ---")
        build_cmd = (
            "pip install . --no-build-isolation -v "
            "-Csetup-args=\"-Dfortran_args=-fallow-argument-mismatch\" "
            "-Csetup-args=\"-Dc_args=-Wno-error=implicit-function-declaration\" "
            "-Csetup-args=\"-Dc_args=-Wno-implicit-int\""
        )

        steps = [
            "pip install numpy==1.26.4 cython==3.0.10 pythran==0.15.0 pybind11==2.12.0 meson-python ninja",
            build_cmd
        ]
        
        # Run dependencies first, then build
        for cmd in steps:
            print(f"\n--- Running: {cmd[:60]}... ---")
            output, exit_code = executor.execute_shell(cmd)
            print(output)
            if exit_code != 0:
                break
        # executor.execute_shell("pip install numpy==1.26.4 cython==3.0.10 pythran==0.15.0 pybind11==2.12.0 meson-python ninja")
        # output, exit_code = executor.execute_shell(build_cmd)
        # print(output)
