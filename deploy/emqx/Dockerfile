# EMQX 5.8.x (последната Apache 2.0 линия — ADR-001) + bootstrap на потребителите
FROM emqx/emqx:5.8.8

USER root
COPY entrypoint.sh /meshgate-entrypoint.sh
RUN chmod +x /meshgate-entrypoint.sh \
    && mkdir -p /opt/emqx/bootstrap \
    && chown -R emqx:emqx /opt/emqx/bootstrap
USER emqx

ENTRYPOINT ["/meshgate-entrypoint.sh"]
CMD ["/opt/emqx/bin/emqx", "foreground"]
