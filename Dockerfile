FROM ghcr.io/named-data/mini-ndn:master

# Install Go 1.24
RUN wget -q https://go.dev/dl/go1.24.1.linux-amd64.tar.gz -O /tmp/go.tar.gz && \
    rm -rf /usr/local/go && tar -C /usr/local -xzf /tmp/go.tar.gz && \
    rm /tmp/go.tar.gz
ENV PATH="/usr/local/go/bin:/root/go/bin:${PATH}"

# Install NDNd
RUN go install github.com/named-data/ndnd/cmd/ndnd@latest && \
    cp /root/go/bin/ndnd /usr/local/bin/

# Copy Mini-NDN integration modules
COPY emu/ndnd.py   /mini-ndn/minindn/apps/ndnd.py
COPY emu/dv.py     /mini-ndn/minindn/apps/dv.py
COPY emu/dv_util.py /mini-ndn/minindn/helpers/dv_util.py

# Copy experiment scripts
COPY emu/ /root/atlas-scenarios/emu/

WORKDIR /root/atlas-scenarios

ENTRYPOINT ["/root/atlas-scenarios/emu/run.sh"]
CMD ["emu/ndnd_demo.py"]
