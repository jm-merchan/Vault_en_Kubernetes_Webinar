FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /src
COPY pom.xml .
COPY src ./src
RUN mvn -q -DskipTests package

FROM eclipse-temurin:17-jre
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/target/app.jar /app.jar
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENV LOOP_INTERVAL_MS=20000
ENTRYPOINT ["/entrypoint.sh"]
