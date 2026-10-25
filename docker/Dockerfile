ARG ES_VERSION
FROM docker.elastic.co/elasticsearch/elasticsearch:${ES_VERSION}

USER root

# vim for editing elasticsearch.yml from `./ece shell <node>`
RUN microdnf install -y --nodocs vim-enhanced && microdnf clean all

# Snapshot repository root (path.repo). A named volume mounted here starts as a
# copy of this directory, so the subdirectories and ownership carry over.
RUN mkdir -p /usr/share/elasticsearch/snapshots/a \
             /usr/share/elasticsearch/snapshots/b \
             /usr/share/elasticsearch/snapshots/shared \
 && chown -R 1000:0 /usr/share/elasticsearch/snapshots

COPY config/ /usr/share/elasticsearch/ece-config/
COPY instances.yml gen-certs.sh ece-entrypoint.sh /usr/share/elasticsearch/ece/
RUN chmod 755 /usr/share/elasticsearch/ece/*.sh

USER 1000:0

ENTRYPOINT ["/bin/tini", "--", "/usr/share/elasticsearch/ece/ece-entrypoint.sh"]
CMD ["eswrapper"]
