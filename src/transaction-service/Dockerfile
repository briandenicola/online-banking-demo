FROM mcr.microsoft.com/dotnet/sdk:9.0-alpine AS build
WORKDIR /src

# Copy shared Contracts project
COPY src/shared/Contracts/*.csproj ./shared/Contracts/
RUN dotnet restore "./shared/Contracts/Contracts.csproj"

# Copy transaction-service project
COPY src/transaction-service/*.csproj ./transaction-service/
RUN dotnet restore "./transaction-service/transaction-service.csproj"

# Copy everything else
COPY src/shared/Contracts/. ./shared/Contracts/
COPY src/transaction-service/. ./transaction-service/

WORKDIR /src/transaction-service
RUN dotnet publish -c Release -o /app/publish

FROM mcr.microsoft.com/dotnet/aspnet:9.0-alpine AS runtime
WORKDIR /app
COPY --from=build /app/publish .
ENTRYPOINT ["dotnet", "transaction-service.dll"]