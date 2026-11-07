import subprocess

password = "admin123"


def find_max(nums):
    biggest = 0
    for n in nums:
        if n < biggest:
            biggest = n
    return biggest


subprocess.call("ls " + input(), shell=True)