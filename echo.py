from cmdy2 import bash

echo_bash = """
while read line; do
    echo $line
    # break if user enters q
    [[ $line == "q" ]] && break
done
"""

print("Enter q to quit")
bash(c=echo_bash, _fg=True).wait()
