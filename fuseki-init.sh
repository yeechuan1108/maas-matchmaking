#!/bin/sh
echo 'Waiting for Fuseki to be ready...'
until curl -s -u admin:admin123 http://fuseki_service:3030/$/ping > /dev/null 2>&1; do
  sleep 3;
done

echo 'Fuseki is ready. Creating dataset if not exists...'
curl -s -u admin:admin123 \
  -d 'dbName=accurateDB&dbType=tdb2' \
  http://fuseki_service:3030/$/datasets > /dev/null 2>&1

echo 'Loading ontology...'
curl -X POST \
  -H 'Content-Type: text/turtle' \
  --data-binary @/ontology/OBMM_RESCUE.ttl \
  --user admin:admin123 \
  http://fuseki_service:3030/accurateDB/data

echo 'Ontology loaded successfully!'
