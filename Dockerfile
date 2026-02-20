FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip software-properties-common && \
    pip3 install ansible passlib && \
    rm -rf /var/lib/apt/lists/*

COPY ansible/ /tmp/ansible/
COPY configs/ /opt/conclave/configs/
COPY dashboard/ /opt/dashboard/
COPY skills/ /opt/conclave/skills-src/

RUN cd /tmp/ansible && ansible-playbook -i inventory.yml playbook.yml

# Clean up Ansible
RUN pip3 uninstall -y ansible ansible-core passlib && \
    rm -rf /tmp/ansible /root/.ansible && \
    apt-get purge -y software-properties-common && \
    apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY scripts/ /opt/conclave/scripts/
RUN chmod +x /opt/conclave/scripts/*.sh

EXPOSE 8888 22 8008 1337 8000 3100 11434 8080 7681
EXPOSE 52000-52100/udp

HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD /opt/conclave/scripts/healthcheck.sh

ENTRYPOINT ["/opt/conclave/scripts/startup.sh"]
